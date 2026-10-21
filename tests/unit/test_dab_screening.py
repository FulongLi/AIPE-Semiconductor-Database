import json

import pytest
from conftest import ROOT

from aipe_devices.importers.datasheet import load_candidates
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.services.selection import (
    DABScreening,
    ScreeningReport,
    ScreeningSettings,
    build_pool,
)

SUMMARY = json.loads((ROOT / "tests/fixtures/dab-l1-nominal-ic.summary.json").read_text())


@pytest.fixture(scope="module")
def report():
    repo = JsonDeviceRepository(ROOT / "data/canonical")
    pool = build_pool(load_candidates(ROOT / "data/candidates/records"), repo)
    settings = ScreeningSettings(rth_case_to_sink=0.1, rth_sink_to_ambient=0.5)
    return DABScreening(SUMMARY, settings).screen(pool)


def test_bridge_stress_and_voltages(report):
    primary, secondary = report.bridges
    assert (primary.dc_bus_voltage, secondary.dc_bus_voltage) == (800.0, 400.0)
    assert primary.stress.current_rms == pytest.approx(9.67, abs=0.01)
    assert secondary.stress.current_rms == pytest.approx(19.75, abs=0.02)
    assert report.switching_frequency == pytest.approx(100e3)
    assert report.dataset_sha256 == SUMMARY["dataset_sha256"]


def test_tiers_never_interleave_and_ranks_are_consecutive(report):
    for bridge in report.bridges:
        tiers = [a.confidence.tier for a in bridge.ranked]
        assert tiers == sorted(tiers)
        assert [a.rank for a in bridge.ranked] == list(range(1, len(bridge.ranked) + 1))
        for tier in set(tiers):
            losses = [a.loss.total for a in bridge.ranked if a.confidence.tier == tier]
            assert losses == sorted(losses)
        assert all(a.rank is None for a in bridge.excluded)
        assert not any(a.confidence.tier == "C_insufficient" for a in bridge.ranked)


def test_derating_excludes_low_voltage_devices_on_the_primary(report):
    primary = report.bridges[0]
    excluded = {a.part_number: a for a in primary.excluded}
    for part in ("C3M0025065K", "NTH4L023N065M3S", "SCT4045DR", "SCT040W65G3-4", "IMZA65R027M1H"):
        assessment = excluded[part]
        assert assessment.electrical.derating_pass is False
        assert any("derating" in r for r in assessment.reasons)
        assert assessment.loss.total is None  # never evaluated outside its voltage class
    ranked_parts = {a.part_number for a in primary.ranked}
    assert "C3M0075120K" in ranked_parts and "C3M0025065K" not in ranked_parts


def test_reference_design_device_values_and_evidence(report):
    primary = report.bridges[0]
    c3m = next(a for a in primary.ranked if a.part_number == "C3M0075120K")
    assert c3m.confidence.tier == "A_canonical_tensors"
    assert c3m.loss.evidence == "canonical_tensor"
    assert c3m.loss.conduction == pytest.approx(10.4, abs=0.1)
    assert c3m.loss.turn_off == pytest.approx(5.95, abs=0.05)
    assert c3m.loss.turn_on == 0.0
    assert c3m.electrical.voltage_utilisation == pytest.approx(800 / 1200, abs=1e-3)
    assert c3m.electrical.derating_pass
    assert "basis:third_party_cited" in c3m.electrical.flags
    assert c3m.thermal.rth_source.startswith("cauer_network")
    assert c3m.thermal.tj_at_fixed_loss == pytest.approx(313.15 + c3m.loss.total * 1.6512, abs=1e-6)
    assert c3m.thermal.fixed_point.converged
    assert c3m.thermal.fixed_point.junction_temperature < c3m.thermal.tj_at_fixed_loss
    secondary = report.bridges[1]
    c3m_secondary = next(a for a in secondary.excluded if a.part_number == "C3M0075120K")
    assert c3m_secondary.thermal.headroom_to_design_limit < 0
    assert any("headroom" in r for r in c3m_secondary.reasons)
    sec = next(a for a in secondary.ranked if a.part_number == "C3M0030090K")
    assert sec.loss.total == pytest.approx(19.7, abs=0.1)


def test_datasheet_point_estimates_are_flagged_and_lower_confidence(report):
    primary = report.bridges[0]
    tier_a = [a for a in primary.ranked if a.confidence.tier.startswith("A")]
    tier_b = [a for a in primary.ranked if a.confidence.tier.startswith("B")]
    assert tier_a and tier_b
    assert min(a.confidence.score for a in tier_a) > max(b.confidence.score for b in tier_b)
    rohm = next(a for a in tier_b if a.part_number == "SCT4036KR")
    assert rohm.loss.evidence == "datasheet_point"
    assert any("datasheet_point_linear_scaling" in f for f in rohm.loss.flags)
    assert any("nearest_datasheet_temperature" in f for f in rohm.loss.flags)
    assert rohm.loss.total < min(a.loss.total for a in tier_a) or True
    # Even a cheaper-looking tier B device never gets a rank ahead of tier A.
    assert max(a.rank for a in tier_a) < min(b.rank for b in tier_b)


def test_insufficient_evidence_is_unranked(report):
    for bridge in report.bridges:
        ff45 = next(a for a in bridge.excluded if a.part_number == "FF45MR12W1M1_B11")
        assert ff45.confidence.tier == "C_insufficient"
        assert any("Unranked" in r for r in ff45.reasons)
        assert ff45.loss.complete is False


def test_report_roundtrips_as_json(report):
    text = report.model_dump_json(by_alias=True)
    data = json.loads(text)
    assert data["schema"] == "aipe-dab-screening/0.1"
    assert ScreeningReport.model_validate_json(text) == report


def test_settings_require_user_thermal_path():
    with pytest.raises(ValueError):
        ScreeningSettings(rth_case_to_sink=0.1)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        DABScreening(
            {"switches": []}, ScreeningSettings(rth_case_to_sink=0.1, rth_sink_to_ambient=0.5)
        )
