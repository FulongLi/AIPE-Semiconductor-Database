"""DAB loss, screening, measurement-request and candidate-import CLI commands (JSON output)."""

import json
from pathlib import Path

from aipe_devices.storage.artifact_store import atomic_write

DAB_COMMANDS = ("dab-losses", "dab-screen", "measurement-requests", "import-candidates")


def _operating_arguments(parser, *, require_point: bool):
    parser.add_argument("--tj", type=float, required=require_point, default=None, help="K")
    parser.add_argument("--vdc", type=float, required=require_point, default=None, help="V")
    parser.add_argument("--fsw", type=float, required=require_point, default=None, help="Hz")
    parser.add_argument("--rg-on", type=float, default=None, help="Ohm")
    parser.add_argument("--rg-off", type=float, default=None, help="Ohm")
    parser.add_argument("--vgs-on", type=float, default=None, help="V")
    parser.add_argument("--vgs-off", type=float, default=None, help="V")
    parser.add_argument("--allow-extrapolation", action="store_true")


def _thermal_arguments(parser, *, required: bool):
    parser.add_argument("--rth-cs", type=float, required=required, default=None, help="K/W")
    parser.add_argument("--rth-sa", type=float, required=required, default=None, help="K/W")
    parser.add_argument("--ambient", type=float, default=313.15, help="K")


def register_dab_commands(commands):
    losses = commands.add_parser(
        "dab-losses", help="Evaluate DAB switch-position losses from actual waveform stress"
    )
    losses.add_argument("--device", required=True, help="Canonical device ID")
    losses.add_argument("--summary", type=Path, required=True, help="AIPE waveform summary JSON")
    losses.add_argument("--switch", default="S1")
    _operating_arguments(losses, require_point=True)
    losses.add_argument("--repository", type=Path, default=Path("data/canonical"))
    losses.add_argument("--waveforms", type=Path, help="HDF5 dataset for the waveform integral")
    losses.add_argument(
        "--reverse-policy", choices=["gate_aware", "body_diode", "channel"], default="gate_aware"
    )
    _thermal_arguments(losses, required=False)
    losses.add_argument("--output", type=Path)

    screen = commands.add_parser("dab-screen", help="Rank candidate devices per DAB bridge")
    screen.add_argument("--summary", type=Path, required=True)
    screen.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/candidates/records"),
        help="Candidate records directory or a datasheet transcription (YAML/JSON)",
    )
    screen.add_argument("--repository", type=Path, default=Path("data/canonical"))
    screen.add_argument("--include-canonical", nargs="*", default=[], help="Extra canonical IDs")
    _operating_arguments(screen, require_point=False)
    screen.add_argument("--derating", type=float, default=0.70)
    screen.add_argument("--tj-limit", type=float, default=398.15, help="Design Tj limit, K")
    _thermal_arguments(screen, required=True)
    screen.add_argument("--output", type=Path)

    requests = commands.add_parser(
        "measurement-requests", help="Prioritised laboratory requests from loss coverage gaps"
    )
    requests.add_argument("--device", required=True)
    requests.add_argument("--summary", type=Path, required=True)
    requests.add_argument("--switch", default="S1")
    _operating_arguments(requests, require_point=True)
    requests.add_argument("--repository", type=Path, default=Path("data/canonical"))
    requests.add_argument("--tj-limit", type=float, default=398.15)
    _thermal_arguments(requests, required=False)
    requests.add_argument("--sample")
    requests.add_argument("--output", type=Path)

    importer = commands.add_parser(
        "import-candidates", help="Build reviewable candidate records from a transcription"
    )
    importer.add_argument("transcription", type=Path)
    importer.add_argument("--output", type=Path, default=Path("data/candidates/records"))
    importer.add_argument("--repository", type=Path, default=Path("data/canonical"))


def _emit(payload, output):
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    if output is not None:
        atomic_write(output, (text + "\n").encode("utf-8"))
    print(text)


def _evaluate(args):
    from aipe_devices.repository.json_repository import JsonDeviceRepository
    from aipe_devices.services.interpolation import EnvelopePolicy
    from aipe_devices.services.loss.dab import DABLossEvaluator, operating_point
    from aipe_devices.services.loss.stress import (
        load_hdf5_switch_waveform,
        stress_from_summary,
        stress_from_waveform,
    )

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    device = JsonDeviceRepository(args.repository).get(args.device)
    stress = stress_from_summary(summary, args.switch)
    waveforms = getattr(args, "waveforms", None)
    if waveforms is not None:
        window = summary.get("window") or {}
        span = (float(window["t0"]), float(window["t1"])) if window else None
        waveform, digest = load_hdf5_switch_waveform(waveforms, args.switch, window=span)
        stress = stress_from_waveform(
            waveform,
            switch_id=args.switch,
            switching_frequency=args.fsw,
            bridge=stress.bridge,
            dataset_sha256=digest or stress.dataset_sha256,
        )
    op = operating_point(
        junction_temperature=args.tj,
        dc_bus_voltage=args.vdc,
        switching_frequency=args.fsw,
        gate_resistance_on=args.rg_on,
        gate_resistance_off=args.rg_off,
        gate_voltage_on=args.vgs_on,
        gate_voltage_off=args.vgs_off,
    )
    evaluator = DABLossEvaluator(
        stress,
        policy=EnvelopePolicy(allow_extrapolation=args.allow_extrapolation),
        reverse_conduction=getattr(args, "reverse_policy", "gate_aware"),
    )
    return device, evaluator.evaluate_detailed(device=device, operating_point=op), stress


def _thermal_block(device, result, args, stress):
    from aipe_devices.services.interpolation import EnvelopePolicy
    from aipe_devices.services.loss.dab import DABLossEvaluator, operating_point
    from aipe_devices.services.thermal import ThermalEvaluator, electro_thermal_fixed_point

    if (
        args.rth_cs is None
        or args.rth_sa is None
        or not device.thermal
        or result.total_loss is None
    ):
        return None
    thermal = ThermalEvaluator()
    network = device.thermal[0]
    sink = args.ambient + result.total_loss * args.rth_sa
    steady = thermal.junction_temperature(
        network,
        result.total_loss,
        rth_case_to_sink=args.rth_cs,
        sink_temperature=sink,
        result_id=f"{device.device_id}:{result.switch_id}:junction_temperature",
    )
    rth = thermal.steady_state_resistance(network).value + args.rth_cs + args.rth_sa

    def loss_at(tj):
        op = operating_point(
            junction_temperature=tj,
            dc_bus_voltage=args.vdc,
            switching_frequency=args.fsw,
            gate_resistance_on=args.rg_on,
            gate_resistance_off=args.rg_off,
            gate_voltage_on=args.vgs_on,
            gate_voltage_off=args.vgs_off,
        )
        evaluated = DABLossEvaluator(
            stress,
            policy=EnvelopePolicy(allow_extrapolation=args.allow_extrapolation),
            reverse_conduction=getattr(args, "reverse_policy", "gate_aware"),
        ).evaluate_detailed(device=device, operating_point=op)
        if evaluated.total_loss is None:
            raise ValueError("incomplete loss evaluation")
        return evaluated.total_loss

    fixed = electro_thermal_fixed_point(
        loss_at,
        rth_junction_to_sink=rth,
        sink_temperature=args.ambient,
        tj_initial=args.tj,
        tolerance=0.05,
        relaxation=0.7,
    )
    return {
        "rth_junction_to_case": thermal.steady_state_resistance(network).value,
        "rth_case_to_sink": args.rth_cs,
        "rth_sink_to_ambient": args.rth_sa,
        "ambient_temperature": args.ambient,
        "steady_state_at_evaluated_loss": steady.model_dump(mode="json"),
        "electro_thermal_fixed_point": fixed.model_dump(mode="json"),
        "foster_equivalent": thermal.foster_equivalent(network).model_dump(mode="json"),
    }


def handle_dab_command(args):
    if args.command == "dab-losses":
        device, result, stress = _evaluate(args)
        payload = {
            "schema": "aipe-dab-loss-evaluation/0.1",
            "result": result.model_dump(mode="json"),
            "thermal": _thermal_block(device, result, args, stress),
        }
        _emit(payload, args.output)
    elif args.command == "measurement-requests":
        from aipe_devices.services.measurement_requests import generate_dab_measurement_requests

        device, result, stress = _evaluate(args)
        headroom = None
        thermal = _thermal_block(device, result, args, stress)
        if thermal is not None:
            headroom = (
                args.tj_limit - thermal["steady_state_at_evaluated_loss"]["quantity"]["value"]
            )
        request = generate_dab_measurement_requests(
            device,
            result,
            thermal_headroom=headroom,
            design_tj_limit=args.tj_limit,
            ambient_temperature=args.ambient,
            physical_sample_id=args.sample,
        )
        _emit(request.model_dump_json(indent=2, by_alias=True), args.output)
    elif args.command == "dab-screen":
        from aipe_devices.importers.datasheet import DatasheetImporter, load_candidates
        from aipe_devices.repository.json_repository import JsonDeviceRepository
        from aipe_devices.services.selection import DABScreening, ScreeningSettings, build_pool

        repository = JsonDeviceRepository(args.repository)
        if args.candidates.is_dir():
            candidates = load_candidates(args.candidates)
        else:
            candidates = DatasheetImporter(repository).load(args.candidates)
        pool = build_pool(candidates, repository, args.include_canonical)
        settings = ScreeningSettings(
            junction_temperature=args.tj if args.tj is not None else 398.15,
            gate_resistance_on=args.rg_on if args.rg_on is not None else 2.0,
            gate_resistance_off=args.rg_off if args.rg_off is not None else 2.0,
            gate_voltage_on=args.vgs_on if args.vgs_on is not None else 15.0,
            gate_voltage_off=args.vgs_off if args.vgs_off is not None else -4.0,
            derating_limit=args.derating,
            rth_case_to_sink=args.rth_cs,
            rth_sink_to_ambient=args.rth_sa,
            ambient_temperature=args.ambient,
            design_tj_limit=args.tj_limit,
            allow_extrapolation=args.allow_extrapolation,
        )
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        report = DABScreening(summary, settings).screen(pool)
        _emit(report.model_dump_json(indent=2, by_alias=True), args.output)
    elif args.command == "import-candidates":
        from aipe_devices.importers.datasheet import DatasheetImporter, write_candidates
        from aipe_devices.repository.json_repository import JsonDeviceRepository

        importer = DatasheetImporter(JsonDeviceRepository(args.repository))
        imports = importer.load(args.transcription)
        report = write_candidates(imports, args.output)
        _emit(report, None)
