"""Regenerate examples/dab from the nominal DAB run summary kept as a test fixture."""

import json
from pathlib import Path

from aipe_devices.importers.datasheet import load_candidates
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.services.loss.dab import DABLossEvaluator, operating_point
from aipe_devices.services.loss.stress import stress_from_summary
from aipe_devices.services.measurement_requests import generate_dab_measurement_requests
from aipe_devices.services.selection import DABScreening, ScreeningSettings, build_pool
from aipe_devices.services.thermal import ThermalEvaluator, electro_thermal_fixed_point

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "tests/fixtures/dab-l1-nominal-ic.summary.json"
OUTPUT = ROOT / "examples/dab"
RTH_CS, RTH_SA, AMBIENT = 0.1, 0.5, 313.15


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def main():
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    repo = JsonDeviceRepository(ROOT / "data/canonical")
    thermal = ThermalEvaluator()
    cases = (
        ("wolfspeed_c3m0075120k", "S1", 800.0, 2.0, 2.0),
        ("wolfspeed_c3m0030090k", "S5", 400.0, 2.5, 2.5),
    )
    for device_id, switch, vdc, rg_on, rg_off in cases:
        device = repo.get(device_id)
        stress = stress_from_summary(summary, switch)

        def evaluate(tj, _device=device, _stress=stress, _vdc=vdc, _on=rg_on, _off=rg_off):
            op = operating_point(
                junction_temperature=tj,
                dc_bus_voltage=_vdc,
                switching_frequency=100e3,
                gate_resistance_on=_on,
                gate_resistance_off=_off,
                gate_voltage_on=15.0,
                gate_voltage_off=-4.0,
            )
            return DABLossEvaluator(_stress).evaluate_detailed(device=_device, operating_point=op)

        result = evaluate(398.15)
        network = device.thermal[0]
        rth = thermal.steady_state_resistance(network).value + RTH_CS + RTH_SA
        fixed = electro_thermal_fixed_point(
            lambda tj: evaluate(tj).total_loss,
            rth_junction_to_sink=rth,
            sink_temperature=AMBIENT,
            tj_initial=398.15,
            tolerance=0.05,
            relaxation=0.7,
        )
        payload = {
            "schema": "aipe-dab-loss-evaluation/0.1",
            "result": result.model_dump(mode="json"),
            "thermal": {
                "rth_junction_to_case": thermal.steady_state_resistance(network).value,
                "rth_case_to_sink": RTH_CS,
                "rth_sink_to_ambient": RTH_SA,
                "ambient_temperature": AMBIENT,
                "steady_state_at_evaluated_loss": thermal.junction_temperature(
                    network,
                    result.total_loss,
                    rth_case_to_sink=RTH_CS,
                    sink_temperature=AMBIENT + result.total_loss * RTH_SA,
                    result_id=f"{device_id}:{switch}:junction_temperature",
                ).model_dump(mode="json"),
                "electro_thermal_fixed_point": fixed.model_dump(mode="json"),
                "foster_equivalent": thermal.foster_equivalent(network).model_dump(mode="json"),
            },
        }
        write(
            OUTPUT / f"dab_losses_{device.identity.part_number}_{switch}.json",
            json.dumps(payload, indent=2),
        )
        headroom = (
            398.15 - payload["thermal"]["steady_state_at_evaluated_loss"]["quantity"]["value"]
        )
        request = generate_dab_measurement_requests(device, result, thermal_headroom=headroom)
        write(
            OUTPUT / f"measurement_request_{device.identity.part_number}_{switch}.json",
            request.model_dump_json(indent=2, by_alias=True),
        )
    pool = build_pool(load_candidates(ROOT / "data/candidates/records"), repo)
    settings = ScreeningSettings(
        rth_case_to_sink=RTH_CS, rth_sink_to_ambient=RTH_SA, ambient_temperature=AMBIENT
    )
    report = DABScreening(summary, settings).screen(pool)
    write(OUTPUT / "dab_screening.json", report.model_dump_json(indent=2, by_alias=True))
    print(f"Wrote DAB examples to {OUTPUT}")


if __name__ == "__main__":
    main()
