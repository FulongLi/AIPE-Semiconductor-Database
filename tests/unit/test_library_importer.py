import json

import pytest
from openpyxl import Workbook

from aipe_devices.importers.library import LibraryImporter
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.schema.enums import Origin


@pytest.fixture
def service():
    return LibraryImporter()


def write_csv(tmp_path, text):
    path = tmp_path / "input.csv"
    path.write_text(text, encoding="utf-8")
    return path


IDENTITY = {"manufacturer": "Synthetic", "part_number": "Example"}


def test_excel_multisheet_header_si_lineage_and_transient_storage(tmp_path, service):
    book = Workbook()
    sheet = book.active
    sheet.title = "identity"
    sheet.append(["manufacturer", "part_number"])
    sheet.append(["Synthetic", "Example"])
    sheet = book.create_sheet("switching")
    sheet.append(["SYNTHETIC demonstration, not manufacturer data"])
    sheet.append(["Tj(C)", "Vdc(V)", "Id(A)", "Eon(mJ)", "Eoff(mJ)"])
    for t in (25, 125):
        for i in (10, 20):
            sheet.append([t, 800, i, i / 100, i / 200])
    path = tmp_path / "input.xlsx"
    book.save(path)
    session = service.inspect(path, origin=Origin.SYNTHETIC)
    assert session.status == "partial", session.report.errors
    assert session.detected_tables[1].header_row == 2
    device = session.canonical_candidate
    curve = device.switching.curves[0]
    assert [a.name for a in curve.axes] == ["current", "junction_temperature"]
    assert curve.axes[1].values == (298.15, 398.15)
    assert curve.values == pytest.approx((0.0001, 0.0001, 0.0002, 0.0002))
    assert curve.condition.dc_bus_voltage.value == 800
    assert curve.quality.review_status == "unreviewed"
    assert curve.provenance.origin == "synthetic"
    assert curve.provenance.source_locators[-1].original_unit == "mJ"
    assert device.provenance[0].import_metadata.original_filename == "input.xlsx"
    repo = JsonDeviceRepository(tmp_path / "canonical")
    saved = service.save(session, repo)
    assert saved.status == "imported"
    assert saved.report.dataset_status == "partial"
    assert path.exists()  # Never delete the caller's original.
    assert [p.suffix for p in repo.root.iterdir()] == [".json"]
    assert repo.get(device.device_id) == device


@pytest.mark.parametrize("header", ["Loss1", "Eon", "Eon(bananas)", "Eon(V)"])
def test_ambiguous_mapping_or_units_blocks_save(tmp_path, service, header):
    path = write_csv(tmp_path, f"Id(A),{header}\n10,2\n20,3\n")
    session = service.inspect(path, identity=IDENTITY)
    assert session.status == "needs_confirmation"
    repo = JsonDeviceRepository(tmp_path / "out")
    assert service.save(session, repo).status == "needs_confirmation"
    assert repo.list() == ()


def test_explicit_override_and_ignore_are_recorded(tmp_path, service):
    path = write_csv(tmp_path, "Id(A),Loss1,Loss2,Note\n10,2,1,hello\n20,3,2,test\n")
    session = service.inspect(
        path,
        identity=IDENTITY,
        mappings={
            "Loss1": {"semantic": "Eon", "unit": "mJ"},
            "Loss2": {"semantic": "Eoff", "unit": "mJ"},
            "Note": {"ignore": True},
        },
    )
    assert session.status == "partial", session.report.errors
    assert {c.name for c in session.canonical_candidate.switching.curves} == {"Eon", "Eoff"}
    assert session.mappings[0].columns[1].status == "confirmed"
    assert session.canonical_candidate.switching.curves[0].provenance.origin == "unknown"


@pytest.mark.parametrize("unit,value,expected", [("µJ", 2, 2e-6), ("uJ", 3, 3e-6), ("mJ", 4, 4e-3)])
def test_energy_unit_variants(tmp_path, service, unit, value, expected):
    session = service.inspect(write_csv(tmp_path, f"Eon({unit})\n{value}\n"), identity=IDENTITY)
    assert session.canonical_candidate.switching.scalars[0].quantity.value == pytest.approx(
        expected
    )


@pytest.mark.parametrize(
    "header,expected", [("Rds_on(mΩ)", "Ohm"), ("Coss(pF)", "F"), ("Ciss(nF)", "F")]
)
def test_other_unit_variants(tmp_path, service, header, expected):
    session = service.inspect(write_csv(tmp_path, f"{header}\n10\n"), identity=IDENTITY)
    assert session.status == "partial", session.report.errors
    assert session.transformations[0].target == expected


def test_missing_identity_invalid_numbers_and_duplicate_headers(tmp_path, service):
    assert service.inspect(write_csv(tmp_path, "Id(A),Vds(V)\n10,2\n")).status == "failed"
    for body in ("Id(A),Vds(V)\n10,nan\n", "Id(A),Id(A)\n1,2\n", "Id(A),Eon(J)\n1,-2\n"):
        assert service.inspect(write_csv(tmp_path, body), identity=IDENTITY).status == "failed"


def test_duplicate_and_conflicting_rows(tmp_path, service):
    session = service.inspect(
        write_csv(tmp_path, "Id(A),Vds(V)\n10,1\n10,1\n20,2\n"), identity=IDENTITY
    )
    assert session.canonical_candidate.conduction.curves[0].values == (1, 2)
    assert any("duplicate" in w for w in session.warnings)
    bad = service.inspect(write_csv(tmp_path, "Id(A),Vds(V)\n10,1\n10,2\n"), identity=IDENTITY)
    assert bad.status == "failed"


def test_sparse_grid_is_not_filled(tmp_path, service):
    path = write_csv(tmp_path, "Tj(C),Id(A),Eon(mJ)\n25,10,1\n25,20,2\n125,10,3\n")
    session = service.inspect(path, identity=IDENTITY)
    data = session.canonical_candidate.switching
    assert sum(len(c.values) for c in data.curves) + len(data.scalars) == 3
    assert any("sparse" in w for w in session.warnings)


def test_canonical_bypass_engineering_validation_and_conflict(tmp_path, service, device):
    path = tmp_path / "canonical.json"
    path.write_text(device.model_dump_json(), encoding="utf-8")
    session = service.inspect(path)
    assert session.canonical_candidate == device
    assert session.report.source_metadata.original_filename == "canonical.json"
    assert session.mappings == ()
    repo = JsonDeviceRepository(tmp_path / "repo")
    assert service.save(session, repo).status == "imported"
    assert service.save(session, repo).status == "failed"
    data = device.model_dump(mode="json")
    data["switching"]["curves"][0]["values"][0] = -1
    path.write_text(json.dumps(data), encoding="utf-8")
    assert service.inspect(path).status == "failed"


def test_generic_json_uses_same_pipeline(tmp_path, service):
    path = tmp_path / "generic.json"
    path.write_text(
        json.dumps(
            {
                "identity": IDENTITY,
                "conduction": [{"Id(A)": 10, "Vds(V)": 1}, {"Id(A)": 20, "Vds(V)": 2}],
            }
        )
    )
    session = service.inspect(path)
    assert session.status == "partial", session.report.errors
    assert session.canonical_candidate.conduction.curves[0].values == (1, 2)


def test_missing_file_and_unsupported_format_report(tmp_path, service):
    assert service.inspect(tmp_path / "absent.xlsx").report.errors
    assert service.inspect(tmp_path / "unsupported.pdf").status == "failed"


@pytest.mark.parametrize("unit", ["ns", "us", "µs"])
def test_time_units_import_without_guessing(tmp_path, service, unit):
    session = service.inspect(
        write_csv(tmp_path, f"Id(A),tr({unit})\n10,2\n20,3\n"), identity=IDENTITY
    )
    assert session.status == "partial"
    assert session.canonical_candidate.switching.curves[0].unit == "s"


def test_capacitance_table_uses_vds_as_independent_variable(tmp_path, service):
    session = service.inspect(
        write_csv(tmp_path, "Vds(V),Coss(pF),Tj(C)\n0,100,25\n800,20,25\n"), identity=IDENTITY
    )
    assert session.status == "partial"
    assert not session.canonical_candidate.conduction.curves
    curve = session.canonical_candidate.capacitance.curves[0]
    assert curve.axes[0].name == "drain_source_voltage"
    assert curve.values == pytest.approx((1e-10, 2e-11))


def test_bad_mapping_shape_and_identity_conflict_are_reported(tmp_path, service):
    path = write_csv(tmp_path, "manufacturer,part_number,Id(A),Vds(V)\nA,X,10,1\nB,X,20,2\n")
    session = service.inspect(path)
    assert session.status == "failed"
    assert session.report.device_identity_status == "conflicting"
    assert service.inspect(path, mappings=[]).status == "failed"
