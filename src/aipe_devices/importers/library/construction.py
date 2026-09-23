"""Build dense canonical curves only from observed coordinates; never fill gaps."""

from collections import defaultdict
from itertools import product
from math import prod

from aipe_devices.domain.conditions import CONDITION_UNITS, ConditionParameter, OperatingCondition
from aipe_devices.domain.curves import Axis, CharacteristicData, Curve, ScalarRecord
from aipe_devices.domain.device import CHARACTERISTICS, PowerSemiconductorDevice
from aipe_devices.domain.identity import Classification, DeviceIdentity
from aipe_devices.domain.provenance import Dependency, Provenance, Source, SourceLocator
from aipe_devices.domain.quality import Quality
from aipe_devices.normalizers.units import normalize
from aipe_devices.schema.enums import DERIVED_ORIGINS, Availability, Lifecycle

from .mapping import FIELDS

AXIS_ORDER = (
    "drain_current",
    "junction_temperature",
    "dc_bus_voltage",
    "gate_resistance_on",
    "gate_resistance_off",
    "drain_source_voltage",
)


def make_condition(values):
    return OperatingCondition(
        **{k: v for k, v in values.items() if k in CONDITION_UNITS},
        extensions=tuple(
            ConditionParameter(name=k, quantity=v)
            for k, v in values.items()
            if k not in CONDITION_UNITS
        ),
    )


def build_device(tables, mappings, metadata, identity, origin, warnings, errors):
    identity = dict(identity or {})
    grouped = defaultdict(list)
    source = Source(
        id=f"upload-{metadata.source_sha256[:16]}",
        kind="user_upload",
        name=metadata.original_filename,
        import_metadata=metadata,
    )
    provenance = Provenance(
        origin=origin,
        source_ids=(source.id,),
        lifecycle=Lifecycle.DERIVED if origin in DERIVED_ORIGINS else Lifecycle.CANONICAL,
        dependencies=(
            Dependency(
                id=f"input:{metadata.source_sha256}", version="1", checksum=metadata.source_sha256
            ),
        ),
    )
    for table, mapping in zip(tables, mappings):
        usable = [
            m
            for m in mapping.columns
            if m.status in {"confirmed", "high_confidence"} and not m.ignored
        ]
        semantics = [m.semantic for m in usable]
        if len(semantics) != len(set(semantics)):
            errors.append(f"{table.info.name}: multiple columns map to the same semantic")
            continue
        seen_rows = set()
        for row_number, row in table.rows:
            row_key = repr(sorted(row.items()))
            if row_key in seen_rows:
                warnings.append(f"{table.info.name} row {row_number}: duplicate row skipped")
                continue
            seen_rows.add(row_key)
            quantities, locators = {}, {}
            for m in usable:
                raw = row.get(m.column)
                if raw is None or raw == "":
                    continue
                group, _, _ = FIELDS[m.semantic]
                if group == "identity":
                    raw = str(raw).strip()
                    if m.semantic in identity and str(identity[m.semantic]) != raw:
                        errors.append(f"Conflicting identity {m.semantic}: {raw}")
                    else:
                        identity[m.semantic] = raw
                    continue
                try:
                    if isinstance(raw, bool):
                        raise ValueError("Boolean is not an engineering value")
                    quantity = normalize(float(raw), m.unit)
                    quantities[m.semantic] = quantity
                    locators[m.semantic] = SourceLocator(
                        sheet=table.info.name,
                        column=m.column,
                        row=row_number,
                        original_value=raw,
                        original_unit=m.unit,
                        canonical_value=quantity.value,
                        canonical_unit=quantity.unit,
                    )
                except (ValueError, TypeError) as exc:
                    errors.append(f"{table.info.name}!{m.column} row {row_number}: {exc}")
            conditions = {k: v for k, v in quantities.items() if FIELDS[k][0] == "condition"}
            for metric, q in quantities.items():
                group = FIELDS[metric][0]
                if group == "condition":
                    continue
                key = (group, metric, tuple(sorted(conditions)))
                grouped[key].append(
                    (conditions, q, tuple(locators[k] for k in (*conditions, metric)))
                )
    if not identity.get("manufacturer") or not identity.get("part_number"):
        errors.append("Missing identity: explicit manufacturer and part_number are required")
        return None
    import re

    device_id = (
        identity.pop("device_id", None)
        or re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{identity['manufacturer']}_{identity['part_number']}")
        .strip("_")
        .lower()
    )
    technology = identity.pop("technology", "unknown")
    records = defaultdict(lambda: {"curves": [], "scalars": []})
    partial_groups = set()
    serial = 0
    for (group, metric, condition_names), points in grouped.items():
        expected = (
            ("junction_temperature", "dc_bus_voltage", "gate_resistance_on", "gate_resistance_off")
            if group == "switching"
            else ("junction_temperature",)
        )
        missing = tuple(n for n in expected if n not in condition_names)
        flags = tuple(f"missing_condition:{n}" for n in missing)
        if missing:
            warnings.append(f"{metric}: unspecified conditions: {', '.join(missing)}")
            partial_groups.add(group)
        coordinates = {}
        for cond, q, loc in points:
            key = tuple(cond[n].value for n in condition_names)
            if key in coordinates:
                if coordinates[key][1] != q:
                    errors.append(
                        f"{metric}: conflicting values at identical conditions; repetitions require explicit handling"
                    )
                else:
                    warnings.append(f"{metric}: repeated identical point retained once")
                continue
            coordinates[key] = (cond, q, loc)
        points = list(coordinates.values())
        varying = [n for n in condition_names if len({p[0][n].value for p in points}) > 1]
        varying.sort(key=lambda n: AXIS_ORDER.index(n) if n in AXIS_ORDER else len(AXIS_ORDER))
        chunks = [points]
        if prod(len({p[0][n].value for p in points}) for n in varying) != len(points):
            # Ragged grids become exact one-dimensional traces at fixed remaining conditions.
            partial_groups.add(group)
            warnings.append(f"{metric}: sparse grid split into exact traces; no interpolation")
            primary = varying[0]
            chunks_by_slice = defaultdict(list)
            for point in points:
                chunks_by_slice[
                    tuple(point[0][n].value for n in condition_names if n != primary)
                ].append(point)
            chunks = list(chunks_by_slice.values())
        for chunk in chunks:
            serial += 1
            names = [n for n in varying if len({p[0][n].value for p in chunk}) > 1]
            fixed = {n: chunk[0][0][n] for n in condition_names if n not in names}
            condition = make_condition(fixed)
            by_key = {tuple(p[0][n].value for n in names): p for p in chunk}
            axes = tuple(
                Axis(
                    name="current" if n == "drain_current" else n,
                    unit=chunk[0][0][n].unit,
                    values=tuple(sorted({p[0][n].value for p in chunk})),
                )
                for n in names
            )
            ordered = [by_key[key] for key in product(*(a.values for a in axes))]
            prov = provenance.model_copy(
                update={"source_locators": tuple(locator for p in ordered for locator in p[2])}
            )
            common = dict(
                id=f"{device_id}:{metric}:{serial}",
                name=metric,
                provenance=prov,
                condition=condition,
                quality=Quality(flags=flags),
            )
            if axes:
                records[group]["curves"].append(
                    Curve(
                        **common,
                        axes=axes,
                        values=tuple(p[1].value for p in ordered),
                        unit=ordered[0][1].unit,
                    )
                )
            else:
                records[group]["scalars"].append(ScalarRecord(**common, quantity=chunk[0][1]))
    characteristics = {}
    for group in CHARACTERISTICS:
        data = records[group]
        names = {r.name for kind in data.values() for r in kind}
        if group == "switching" and not {"Eon", "Eoff"} <= names:
            partial_groups.add(group)
        state = (
            Availability.MISSING
            if not names
            else (Availability.PARTIAL if group in partial_groups else Availability.AVAILABLE)
        )
        characteristics[group] = CharacteristicData(
            availability=state, curves=tuple(data["curves"]), scalars=tuple(data["scalars"])
        )
    return PowerSemiconductorDevice(
        device_id=device_id,
        identity=DeviceIdentity(**identity),
        classification=Classification(technology=technology),
        provenance=(source,),
        **characteristics,
    )
