"""Datasheet transcription importer: reviewable candidate records, never canonical data.

A structured JSON/YAML transcription (``aipe-datasheet-transcription/0.1``) lists the
values a manufacturer datasheet prints, with units and test conditions exactly as
printed. The importer converts them to SI ``ScalarRecord`` entries with
``manufacturer_datasheet`` origin, keeps the datasheet URL/revision as source
evidence, records which quantities are absent and never estimates a missing value.
Candidate records stay ``review_status: unreviewed`` and live outside
``data/canonical``. When a canonical record for the same manufacturer/part exists, the
candidate is linked to it through an ``AIPE`` source carrying the record URN.

No PDF is parsed or copied; the transcription itself is the reviewable artefact.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from aipe_devices.domain.base import Model
from aipe_devices.domain.conditions import CONDITION_UNITS, ConditionParameter, OperatingCondition
from aipe_devices.domain.curves import CharacteristicData, ScalarRecord
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.identity import Classification, DeviceIdentity
from aipe_devices.domain.models import ModelReference
from aipe_devices.domain.module import DevicePackage
from aipe_devices.domain.provenance import AccessMetadata, Provenance, Source, SourceLocator
from aipe_devices.domain.quality import Quality
from aipe_devices.domain.quantities import Quantity
from aipe_devices.importers.plecs import device_key
from aipe_devices.normalizers.units import normalize
from aipe_devices.schema.enums import Availability, Lifecycle, Origin, Statistic, Technology
from aipe_devices.schema.validation import ValidationReport
from aipe_devices.services.validation import validate_device
from aipe_devices.storage.artifact_store import atomic_write

TRANSCRIPTION_SCHEMA = "aipe-datasheet-transcription/0.1"
Basis = Literal["manufacturer_specified", "third_party_cited", "product_page"]

# yaml key -> (device group, canonical record name, canonical unit)
FIELDS = {
    "ratings": {
        "vds_max": ("ratings", "vds_max", "V"),
        "id_max": ("ratings", "id_max", "A"),
        "tj_max": ("ratings", "tj_max", "K"),
        "pd_max": ("ratings", "pd_max", "W"),
        "v_isolation_rms": ("ratings", "v_isolation_rms", "V"),
    },
    "conduction": {"rds_on": ("conduction", "rds_on", "Ohm")},
    "reverse_conduction": {
        "vsd": ("reverse_conduction", "voltage_drop", "V"),
        "qrr": ("reverse_conduction", "Qrr", "C"),
        "trr": ("reverse_conduction", "trr", "s"),
        "irrm": ("reverse_conduction", "Irrm", "A"),
        "qfr": ("reverse_conduction", "Qfr", "C"),
        "tfr": ("reverse_conduction", "tfr", "s"),
        "ifrm": ("reverse_conduction", "Ifrm", "A"),
    },
    "switching": {
        "Eon": ("switching", "Eon", "J"),
        "Eoff": ("switching", "Eoff", "J"),
        "Err": ("switching", "Err", "J"),
    },
    "capacitance": {
        "ciss": ("capacitance", "ciss", "F"),
        "coss": ("capacitance", "coss", "F"),
        "crss": ("capacitance", "crss", "F"),
        "eoss": ("capacitance", "Eoss", "J"),
        "qoss": ("capacitance", "qoss", "C"),
        "co_er": ("capacitance", "co_er", "F"),
        "co_tr": ("capacitance", "co_tr", "F"),
    },
    "gate_charge": {
        "qg_total": ("gate_charge", "qg_total", "C"),
        "qgs": ("gate_charge", "qgs", "C"),
        "qgd": ("gate_charge", "qgd", "C"),
    },
    "gate_drive": {
        "vgs_on_recommended": ("gate_charge", "vgs_on_recommended", "V"),
        "vgs_off_recommended": ("gate_charge", "vgs_off_recommended", "V"),
        "vgs_rating_max": ("gate_charge", "vgs_rating_max", "V"),
        "vgs_rating_min": ("gate_charge", "vgs_rating_min", "V"),
        "rg_internal": ("gate_charge", "rg_internal", "Ohm"),
    },
    "thermal": {
        "rth_jc": ("package", "rth_jc", "K/W"),
        "rth_jhs": ("package", "rth_jhs", "K/W"),
    },
    "package_parasitics": {"lstray": ("package", "lstray", "H")},
}
EXTENSION_UNITS = {
    "drain_source_voltage": "V",
    "measurement_frequency": "Hz",
    "test_inductance": "H",
    "di_dt": "A/s",
    "heatsink_temperature": "K",
}
GROUPS = ("conduction", "switching", "capacitance", "gate_charge", "reverse_conduction")


class TQuantity(Model):
    value: float
    unit: str


class TPoint(Model):
    value: float
    unit: str
    statistic: Literal["unspecified", "typical", "minimum", "maximum"] = "unspecified"
    conditions: dict[str, TQuantity] = {}
    flags: tuple[str, ...] = ()
    note: str | None = None
    basis: Basis = "manufacturer_specified"


class TDatasheet(Model):
    url: str
    revision: str | None = None
    date: str | None = None
    document_id: str | None = None


class TCitation(Model):
    kind: Literal["paper", "manufacturer", "AIPE", "distributor"]
    name: str
    url: str | None = None
    locator: str | None = None


class TModels(Model):
    formats: tuple[str, ...] = ()
    availability: str | None = None
    licence_note: str | None = None
    url: str | None = None
    retrieved: bool = False


PointGroup = dict[str, TPoint | list[TPoint]]


class TDevice(Model):
    part_number: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    technology: Technology = Technology.SIC_MOSFET
    integration: Literal["discrete", "module", "unknown"] = "unknown"
    package: str | None = None
    family: str | None = None
    description: str | None = None
    status: str | None = None
    product_page: str | None = None
    datasheet: TDatasheet | None = None
    cited_by: TCitation | None = None
    ratings: PointGroup = {}
    conduction: PointGroup = {}
    reverse_conduction: PointGroup = {}
    switching: PointGroup = {}
    capacitance: PointGroup = {}
    gate_charge: PointGroup = {}
    gate_drive: PointGroup = {}
    thermal: PointGroup = {}
    package_parasitics: PointGroup = {}
    models: TModels | None = None
    informational: dict[str, TQuantity] = {}
    absent: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class Transcription(Model):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, populate_by_name=True
    )
    transcription_schema: Literal["aipe-datasheet-transcription/0.1"] = Field(alias="schema")
    title: str
    collected_on: str
    transcribed_from: str
    conventions: tuple[str, ...] = ()
    devices: tuple[TDevice, ...] = Field(min_length=1)


class CanonicalLink(Model):
    device_id: str
    revision: int
    uri: str
    provides: tuple[str, ...]


class CandidateDossier(Model):
    """Review context that has no place in the device schema."""

    candidate_id: str
    manufacturer: str
    part_number: str
    package: str | None
    family: str | None
    status: str | None
    description: str | None
    datasheet: TDatasheet | None
    cited_by: TCitation | None
    product_page: str | None
    models: TModels | None
    field_basis: dict[str, Basis]
    absent: tuple[str, ...]
    informational: dict[str, TQuantity]
    notes: tuple[str, ...]
    canonical_link: CanonicalLink | None
    transcribed_from: str
    collected_on: str
    review_status: Literal["unreviewed"] = "unreviewed"


class CandidateImport(Model):
    device: PowerSemiconductorDevice
    dossier: CandidateDossier
    validation: ValidationReport
    record_count: int


def load_transcription(path: str | Path) -> Transcription:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError("YAML transcriptions need the optional pyyaml package") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return Transcription.model_validate(data)


def _points(group: PointGroup):
    for key, value in group.items():
        for index, point in enumerate(value if isinstance(value, list) else [value]):
            yield key, index, point


def _condition(conditions: dict[str, TQuantity], flags: list[str]):
    fields = {}
    extensions = []
    for name, raw in conditions.items():
        quantity = normalize(raw.value, raw.unit)
        if name == "source_current":
            # Printed as positive source-to-drain current; canonical convention is signed
            # drain current, so reverse conduction is negative.
            quantity = Quantity(value=-quantity.value, unit=quantity.unit)
            name = "drain_current"
            flags.append("sign_convention:source_current_stored_as_negative_drain_current")
        if name == "gate_resistance":
            fields["gate_resistance_on"] = quantity
            fields["gate_resistance_off"] = quantity
            flags.append("single_gate_resistance_printed")
            continue
        if name in CONDITION_UNITS:
            if quantity.unit != CONDITION_UNITS[name]:
                raise ValueError(f"Condition {name} must convert to {CONDITION_UNITS[name]}")
            fields[name] = quantity
        elif name in EXTENSION_UNITS:
            if quantity.unit != EXTENSION_UNITS[name]:
                raise ValueError(f"Condition {name} must convert to {EXTENSION_UNITS[name]}")
            extensions.append(ConditionParameter(name=name, quantity=quantity))
        else:
            raise ValueError(f"Unknown transcription condition {name}")
    return OperatingCondition(**fields, extensions=tuple(extensions))


class DatasheetImporter:
    """Turn a transcription into schema-valid, unreviewed candidate records."""

    def __init__(self, canonical_repository=None):
        self.canonical_repository = canonical_repository

    def load(self, path: str | Path) -> tuple[CandidateImport, ...]:
        transcription = load_transcription(path)
        return tuple(self.build(device, transcription) for device in transcription.devices)

    def build(self, entry: TDevice, transcription: Transcription) -> CandidateImport:
        key = device_key(entry.manufacturer, entry.part_number)
        candidate_id = f"candidate_{key}"
        sources = {}
        if entry.datasheet is not None:
            parts = [entry.datasheet.revision]
            if entry.datasheet.date:
                parts.append(f"({entry.datasheet.date})")
            label = " ".join(x for x in parts if x)
            sources["manufacturer_specified"] = Source(
                id=f"datasheet:{key}",
                kind="manufacturer",
                name=f"{entry.manufacturer} datasheet {entry.part_number} {label}".strip(),
                url=entry.datasheet.url,
                access=AccessMetadata(
                    owner=entry.manufacturer, category="manufacturer", visibility="public"
                ),
            )
        if entry.product_page:
            sources["product_page"] = Source(
                id=f"product-page:{key}",
                kind="manufacturer",
                name=f"{entry.manufacturer} product page {entry.part_number}",
                url=entry.product_page,
                access=AccessMetadata(
                    owner=entry.manufacturer, category="manufacturer", visibility="public"
                ),
            )
        if entry.cited_by is not None:
            sources["third_party_cited"] = Source(
                id=f"citation:{key}",
                kind=entry.cited_by.kind,
                name=entry.cited_by.name,
                url=entry.cited_by.url,
                access=AccessMetadata(visibility="public"),
            )
        if not sources:
            raise ValueError(
                f"{entry.part_number}: a datasheet, product page or citation is needed"
            )
        link = None
        if self.canonical_repository is not None and key in self.canonical_repository.list():
            canonical = self.canonical_repository.get(key)
            provides = []
            for group in ("conduction", "switching", "reverse_conduction"):
                for curve in getattr(canonical, group).curves:
                    provides.append(f"{group}:{curve.name} tensor {curve.id}")
            provides.extend(f"thermal:{t.topology} network {t.id}" for t in canonical.thermal)
            link = CanonicalLink(
                device_id=canonical.device_id,
                revision=canonical.revision,
                uri=f"urn:aipe:semiconductor:{canonical.device_id}:revision:{canonical.revision}",
                provides=tuple(provides),
            )
            sources["canonical"] = Source(
                id=f"canonical:{canonical.device_id}",
                kind="AIPE",
                name=f"AIPE canonical record {canonical.device_id} revision {canonical.revision}",
                url=link.uri,
                access=AccessMetadata(category="aipe", visibility="public"),
            )
        records = {g: [] for g in GROUPS}
        ratings = []
        parasitics = []
        field_basis = {}
        serial = 0
        for section, mapping in FIELDS.items():
            group_points = getattr(entry, section)
            for yaml_key, index, point in _points(group_points):
                if yaml_key not in mapping:
                    raise ValueError(f"{entry.part_number}: unknown {section} field {yaml_key}")
                group, name, unit = mapping[yaml_key]
                source = sources.get(point.basis)
                if source is None:
                    raise ValueError(
                        f"{entry.part_number}: {yaml_key} claims basis {point.basis} without a source"
                    )
                flags = list(point.flags)
                flags.append(f"basis:{point.basis}")
                quantity = normalize(point.value, point.unit)
                if quantity.unit != unit:
                    raise ValueError(
                        f"{entry.part_number}: {yaml_key} converts to {quantity.unit}, expected {unit}"
                    )
                if yaml_key == "vsd":
                    quantity = Quantity(value=-quantity.value, unit=unit)
                    flags.append("sign_convention:third_quadrant_negative_voltage_drop")
                condition = _condition(point.conditions, flags)
                if point.note:
                    flags.append(f"note:{point.note}")
                serial += 1
                record = ScalarRecord(
                    id=f"{candidate_id}:{name}:{serial}",
                    name=name,
                    quantity=quantity,
                    condition=condition,
                    statistic=Statistic(point.statistic),
                    quality=Quality(flags=tuple(flags)),
                    provenance=Provenance(
                        origin=Origin.DATASHEET,
                        source_ids=(source.id,),
                        lifecycle=Lifecycle.VALIDATED,
                        source_locators=(
                            SourceLocator(
                                sheet=section,
                                column=yaml_key,
                                row=index + 1,
                                original_value=point.value,
                                original_unit=point.unit,
                                canonical_value=quantity.value,
                                canonical_unit=quantity.unit,
                            ),
                        ),
                    ),
                )
                field_basis[f"{section}.{yaml_key}"] = point.basis
                if group == "ratings":
                    ratings.append(record)
                elif group == "package":
                    parasitics.append(record)
                else:
                    records[group].append(record)
        flags = ["candidate_not_canonical", "datasheet_transcription"]
        flags.extend(f"absent:{item}" for item in entry.absent)
        if link is not None:
            flags.append(f"linked_canonical:{link.device_id}")
        if entry.cited_by is not None and entry.datasheet is None:
            flags.append("values_cited_by_third_party")
        models = ()
        if entry.models is not None:
            catalogue_source = sources.get("product_page") or next(iter(sources.values()))
            models = (
                ModelReference(
                    id=f"{candidate_id}:manufacturer-models",
                    format="manufacturer_model_catalogue",
                    provenance=Provenance(
                        origin=Origin.DATASHEET,
                        source_ids=(catalogue_source.id,),
                        lifecycle=Lifecycle.VALIDATED,
                    ),
                    adapter_metadata={
                        "formats": list(entry.models.formats),
                        "availability": entry.models.availability,
                        "licence_note": entry.models.licence_note,
                        "url": entry.models.url,
                        "retrieved": entry.models.retrieved,
                        "note": "Catalogue entry only; no model file is stored or redistributed",
                    },
                ),
            )
        characteristics = {
            group: CharacteristicData(
                availability=Availability.PARTIAL if items else Availability.UNKNOWN,
                scalars=tuple(items),
            )
            for group, items in records.items()
        }
        device = PowerSemiconductorDevice(
            device_id=candidate_id,
            identity=DeviceIdentity(
                manufacturer=entry.manufacturer,
                part_number=entry.part_number,
                family_id=entry.family,
                aliases=entry.aliases,
            ),
            classification=Classification(
                technology=entry.technology, integration=entry.integration
            ),
            ratings=tuple(ratings),
            package=DevicePackage(name=entry.package, parasitics=tuple(parasitics)),
            provenance=tuple(sources.values()),
            quality=Quality(flags=tuple(flags), review_status="unreviewed"),
            models=models,
            **characteristics,
        )
        validation = validate_device(device)
        validation.raise_for_errors()
        dossier = CandidateDossier(
            candidate_id=candidate_id,
            manufacturer=entry.manufacturer,
            part_number=entry.part_number,
            package=entry.package,
            family=entry.family,
            status=entry.status,
            description=entry.description,
            datasheet=entry.datasheet,
            cited_by=entry.cited_by,
            product_page=entry.product_page,
            models=entry.models,
            field_basis=field_basis,
            absent=entry.absent,
            informational=entry.informational,
            notes=entry.notes,
            canonical_link=link,
            transcribed_from=transcription.transcribed_from,
            collected_on=transcription.collected_on,
        )
        return CandidateImport(
            device=device,
            dossier=dossier,
            validation=validation,
            record_count=serial,
        )


def write_candidates(imports, directory: str | Path) -> dict:
    """Persist ``<id>.json`` device records, ``<id>.dossier.json`` and an index."""
    directory = Path(directory)
    index = []
    for item in imports:
        atomic_write(
            directory / f"{item.device.device_id}.json",
            (item.device.model_dump_json(indent=2) + "\n").encode("utf-8"),
        )
        atomic_write(
            directory / f"{item.device.device_id}.dossier.json",
            (item.dossier.model_dump_json(indent=2) + "\n").encode("utf-8"),
        )
        index.append(
            {
                "candidate_id": item.device.device_id,
                "manufacturer": item.device.identity.manufacturer,
                "part_number": item.device.identity.part_number,
                "records": item.record_count,
                "absent": list(item.dossier.absent),
                "canonical_link": (
                    item.dossier.canonical_link.device_id if item.dossier.canonical_link else None
                ),
            }
        )
    report = {
        "schema": "aipe-candidate-index/0.1",
        "status": "unreviewed candidates; not canonical evidence",
        "candidates": index,
    }
    atomic_write(directory / "index.json", (json.dumps(report, indent=2) + "\n").encode("utf-8"))
    return report


def load_candidates(directory: str | Path) -> tuple[CandidateImport, ...]:
    """Read persisted candidate records (and dossiers when present)."""
    directory = Path(directory)
    items = []
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".dossier.json") or path.name == "index.json":
            continue
        device = PowerSemiconductorDevice.model_validate_json(path.read_bytes())
        validation = validate_device(device)
        validation.raise_for_errors()
        dossier_path = path.with_name(f"{path.stem}.dossier.json")
        if not dossier_path.exists():
            raise FileNotFoundError(f"Candidate {path.name} has no dossier")
        dossier = CandidateDossier.model_validate_json(dossier_path.read_bytes())
        items.append(
            CandidateImport(
                device=device,
                dossier=dossier,
                validation=validation,
                record_count=sum(
                    1
                    for _ in (
                        *device.ratings,
                        *device.package.parasitics,
                        *(r for g in GROUPS for r in getattr(device, g).scalars),
                    )
                ),
            )
        )
    return tuple(items)
