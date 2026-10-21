import json
import subprocess
import sys

import pytest
from conftest import ROOT

SUMMARY = ROOT / "tests/fixtures/dab-l1-nominal-ic.summary.json"


def cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "aipe_devices.cli", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_dab_losses_command_prints_json_with_thermal_block(tmp_path):
    output = tmp_path / "losses.json"
    result = cli(
        "dab-losses",
        "--device",
        "wolfspeed_c3m0075120k",
        "--summary",
        SUMMARY,
        "--switch",
        "S1",
        "--tj",
        "398.15",
        "--vdc",
        "800",
        "--fsw",
        "100e3",
        "--rg-on",
        "2",
        "--rg-off",
        "2",
        "--vgs-on",
        "15",
        "--vgs-off",
        "-4",
        "--rth-cs",
        "0.1",
        "--rth-sa",
        "0.5",
        "--output",
        output,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["schema"] == "aipe-dab-loss-evaluation/0.1"
    components = {c["name"]: c for c in data["result"]["components"]}
    assert components["conduction_loss"]["value"] == pytest.approx(10.4, abs=0.1)
    assert components["turn_off_loss"]["value"] == pytest.approx(5.95, abs=0.05)
    assert components["turn_on_loss"]["value"] == 0.0
    assert data["result"]["complete"] is True
    assert {n["quantity"] for n in data["result"]["coverage"]} >= {"coss", "Eoss", "vds_max"}
    thermal = data["thermal"]
    assert thermal["steady_state_at_evaluated_loss"]["quantity"]["unit"] == "K"
    assert thermal["electro_thermal_fixed_point"]["converged"] is True
    assert thermal["foster_equivalent"]["topology"] == "Foster"
    assert json.loads(output.read_text(encoding="utf-8")) == data


def test_dab_losses_rejects_out_of_range_gate_resistance_without_policy():
    result = cli(
        "dab-losses",
        "--device",
        "wolfspeed_c3m0030090k",
        "--summary",
        SUMMARY,
        "--switch",
        "S5",
        "--tj",
        "398.15",
        "--vdc",
        "400",
        "--fsw",
        "100e3",
        "--rg-on",
        "2",
        "--rg-off",
        "2",
    )
    assert result.returncode != 0
    assert "PLECS model range" in result.stderr
    allowed = cli(
        "dab-losses",
        "--device",
        "wolfspeed_c3m0030090k",
        "--summary",
        SUMMARY,
        "--switch",
        "S5",
        "--tj",
        "398.15",
        "--vdc",
        "400",
        "--fsw",
        "100e3",
        "--rg-on",
        "2",
        "--rg-off",
        "2",
        "--allow-extrapolation",
    )
    assert allowed.returncode == 0, allowed.stderr
    components = {c["name"]: c for c in json.loads(allowed.stdout)["result"]["components"]}
    assert "extrapolated:gate_resistance_off" in components["turn_off_loss"]["flags"]


def test_dab_screen_and_measurement_requests_commands(tmp_path):
    screen = cli(
        "dab-screen",
        "--summary",
        SUMMARY,
        "--rth-cs",
        "0.1",
        "--rth-sa",
        "0.5",
        "--output",
        tmp_path / "screen.json",
    )
    assert screen.returncode == 0, screen.stderr
    report = json.loads(screen.stdout)
    assert report["schema"] == "aipe-dab-screening/0.1"
    primary = report["bridges"][0]
    assert primary["bridge"] == "primary" and primary["ranked"]
    tiers = [a["confidence"]["tier"] for a in primary["ranked"]]
    assert tiers == sorted(tiers)
    assert any(a["part_number"] == "C3M0075120K" for a in primary["ranked"])
    requests = cli(
        "measurement-requests",
        "--device",
        "wolfspeed_c3m0075120k",
        "--summary",
        SUMMARY,
        "--switch",
        "S1",
        "--tj",
        "398.15",
        "--vdc",
        "800",
        "--fsw",
        "100e3",
        "--rg-on",
        "2",
        "--rg-off",
        "2",
        "--vgs-on",
        "15",
        "--vgs-off",
        "-4",
        "--rth-cs",
        "0.1",
        "--rth-sa",
        "0.5",
    )
    assert requests.returncode == 0, requests.stderr
    data = json.loads(requests.stdout)
    assert data["schema"] == "aipe-prioritised-measurement-request/0.1"
    assert len(data["request"]["test_plan_items"]) == 8
    assert data["priorities"][0]["rank"] == 1
    assert all(item["draft"] for item in data["request"]["test_plan_items"])


def test_import_candidates_command_writes_outside_canonical(tmp_path):
    pytest.importorskip("yaml")
    result = cli(
        "import-candidates",
        ROOT / "data/candidates/sic-dab-shortlist-2026-10-21.yaml",
        "--output",
        tmp_path / "records",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report["candidates"]) == 19
    assert sum(1 for c in report["candidates"] if c["canonical_link"]) == 6
    assert (tmp_path / "records/index.json").exists()
    assert len(list((tmp_path / "records").glob("candidate_*.dossier.json"))) == 19
    assert not list((ROOT / "data/canonical").glob("candidate_*"))
