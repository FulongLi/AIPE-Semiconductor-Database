"""Switch electrical stress derived from actual converter waveforms or their JSON summary.

Two inputs are accepted: the per-switch metrics block of an AIPE DAB waveform summary
(``aipe-dab-waveform-summary/0.1``) or a sampled one-period (or integer-period) switch
current waveform. Both become a ``SwitchStress`` record with explicit sign conventions:
positive current is drain-to-source conduction. No quantity is estimated when the input
does not carry it; absent quantities stay ``None`` and are reported downstream.
"""

from bisect import bisect_left
from math import sqrt
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from aipe_devices.domain.base import Model

SUMMARY_SCHEMA_PREFIX = "aipe-dab-waveform-summary/"


class SwitchWaveform(Model):
    """Sampled switch-pair waveform; time strictly increasing, currents in A."""

    time: tuple[float, ...] = Field(min_length=3)
    current: tuple[float, ...] = Field(min_length=3)
    gate: tuple[float, ...] | None = None
    drain_source_voltage: tuple[float, ...] | None = None

    @model_validator(mode="after")
    def consistent(self):
        n = len(self.time)
        for name in ("current", "gate", "drain_source_voltage"):
            values = getattr(self, name)
            if values is not None and len(values) != n:
                raise ValueError(f"{name} must have one sample per time point")
        if any(b <= a for a, b in zip(self.time, self.time[1:])):
            raise ValueError("Waveform time must be strictly increasing")
        return self

    @property
    def window(self) -> float:
        return self.time[-1] - self.time[0]


class SwitchStress(Model):
    """Per-switch electrical stress for one steady-state window of ``periods`` periods."""

    switch_id: str = Field(min_length=1)
    bridge: str | None = None
    source: Literal["summary_metrics", "sampled_waveform"]
    periods: float = Field(gt=0)
    switching_frequency: float | None = Field(default=None, gt=0)
    current_rms: float = Field(ge=0)
    current_avg: float | None = None
    current_peak_forward: float | None = None
    current_peak_reverse: float | None = None
    conduction_fraction: float | None = Field(default=None, ge=0, le=1)
    forward_charge_per_cycle: float | None = Field(default=None, ge=0)
    reverse_charge_per_cycle: float | None = Field(default=None, le=0)
    turn_off_currents: tuple[float, ...] = ()
    turn_on_currents: tuple[float, ...] = ()
    zvs_turn_on: tuple[bool, ...] = ()
    blocking_voltages: tuple[float, ...] = ()
    v_ds_max: float | None = None
    waveform: SwitchWaveform | None = None
    dataset_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    summary_valid: bool | None = None
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def event_consistency(self):
        if self.zvs_turn_on and len(self.zvs_turn_on) != len(self.turn_on_currents):
            raise ValueError("One ZVS flag per turn-on event is required")
        if self.blocking_voltages and len(self.blocking_voltages) != len(self.turn_off_currents):
            raise ValueError("One blocking voltage per turn-off event is required")
        return self

    def without_waveform(self) -> "SwitchStress":
        return self.model_copy(update={"waveform": None})

    @property
    def reverse_charge_fraction(self) -> float | None:
        """Share of the conducted charge that flows source-to-drain; None when unknown."""
        if self.forward_charge_per_cycle is None or self.reverse_charge_per_cycle is None:
            return None
        total = self.forward_charge_per_cycle + abs(self.reverse_charge_per_cycle)
        return abs(self.reverse_charge_per_cycle) / total if total > 0 else None


def _quantity(block, unit):
    if block is None:
        return None
    if block.get("unit") != unit:
        raise ValueError(f"Summary quantity unit {block.get('unit')} differs from {unit}")
    return float(block["value"])


def stress_from_summary(summary: dict, switch_id: str) -> SwitchStress:
    """Read one switch from an AIPE DAB waveform summary; invalid summaries are rejected."""
    notes = []
    schema = str(summary.get("schema", ""))
    if not schema.startswith(SUMMARY_SCHEMA_PREFIX):
        notes.append(f"Unrecognised summary schema {schema!r}; fields read by name")
    valid = summary.get("valid")
    if valid is False:
        raise ValueError("Waveform summary is marked invalid; losses must not be derived from it")
    if valid is None:
        notes.append("Summary carries no validity flag")
    steady = summary.get("steady_state") or {}
    if steady.get("ok") is False:
        raise ValueError("Waveform summary did not reach steady state")
    switches = {s["id"]: s for s in summary.get("switches", ())}
    if switch_id not in switches:
        raise ValueError(f"Switch {switch_id} is not in the summary ({sorted(switches)})")
    sw = switches[switch_id]
    window = summary.get("window") or {}
    periods = window.get("cycles")
    frequency = None
    if periods and window.get("t1") is not None and window.get("t0") is not None:
        frequency = periods / (float(window["t1"]) - float(window["t0"]))
        frequency = float(f"{frequency:.9g}")
    if not periods:
        periods = sw.get("turn_off_events") or len(sw["turn_off_current"]["values_A"])
        notes.append("Window length taken as one period per turn-off event")
    zvs = sw.get("zvs_current_condition", {}).get("per_event") or ()
    return SwitchStress(
        switch_id=switch_id,
        bridge=sw.get("bridge"),
        source="summary_metrics",
        periods=float(periods),
        switching_frequency=frequency,
        current_rms=_quantity(sw["current_rms"], "A"),
        current_avg=_quantity(sw.get("current_avg"), "A"),
        current_peak_forward=_quantity(sw.get("current_peak_forward"), "A"),
        current_peak_reverse=_quantity(sw.get("current_peak_reverse"), "A"),
        conduction_fraction=_quantity(sw.get("conduction_fraction"), "1"),
        forward_charge_per_cycle=_quantity(sw.get("forward_charge_per_cycle"), "C"),
        reverse_charge_per_cycle=_quantity(sw.get("reverse_charge_per_cycle"), "C"),
        turn_off_currents=tuple(float(v) for v in sw["turn_off_current"]["values_A"]),
        turn_on_currents=tuple(float(v) for v in sw["turn_on_current"]["values_A"]),
        zvs_turn_on=tuple(bool(v) for v in zvs),
        blocking_voltages=tuple(
            float(v) for v in sw.get("v_ds_after_turn_off", {}).get("values_V", ())
        ),
        v_ds_max=_quantity(sw.get("v_ds_max"), "V"),
        dataset_sha256=summary.get("dataset_sha256"),
        summary_valid=valid,
        notes=tuple(notes),
    )


def trapezoid(time, values):
    return sum(
        0.5 * (values[k] + values[k + 1]) * (time[k + 1] - time[k]) for k in range(len(time) - 1)
    )


def _edges(signal, threshold):
    rising = [k for k in range(len(signal) - 1) if signal[k] < threshold <= signal[k + 1]]
    falling = [k for k in range(len(signal) - 1) if signal[k] >= threshold > signal[k + 1]]
    return rising, falling


def _sign_after(current, start, threshold, horizon):
    for k in range(start, min(len(current), start + horizon)):
        if current[k] > threshold:
            return False
        if current[k] < -threshold:
            return True
    return None


def stress_from_waveform(
    waveform: SwitchWaveform,
    *,
    switch_id: str,
    switching_frequency: float,
    bridge: str | None = None,
    threshold_fraction: float = 0.01,
    gate_threshold: float | None = None,
    dataset_sha256: str | None = None,
) -> SwitchStress:
    """Derive stress metrics from a sampled waveform spanning an integer number of periods."""
    t, i = waveform.time, waveform.current
    window = waveform.window
    periods = window * switching_frequency
    if abs(periods - round(periods)) > 0.02 * max(1.0, round(periods)) or round(periods) < 1:
        raise ValueError(
            f"Waveform window {window:.4g} s spans {periods:.3f} periods; supply an integer number"
        )
    periods = float(round(periods))
    peak_fwd = max(i)
    peak_rev = min(i)
    peak = max(abs(peak_fwd), abs(peak_rev), 1e-12)
    threshold = threshold_fraction * peak
    rms = sqrt(trapezoid(t, [x * x for x in i]) / window)
    avg = trapezoid(t, i) / window
    conducting = [1.0 if abs(x) > threshold else 0.0 for x in i]
    conduction_fraction = min(1.0, max(0.0, trapezoid(t, conducting) / window))
    forward_charge = trapezoid(t, [max(x, 0.0) for x in i]) / periods
    reverse_charge = trapezoid(t, [min(x, 0.0) for x in i]) / periods
    horizon = max(2, int(0.02 * len(t) / periods))
    notes = []
    if waveform.gate is not None:
        gate = waveform.gate
        level = gate_threshold if gate_threshold is not None else 0.5 * (max(gate) + min(gate))
        rising, falling = _edges(gate, level)
        turn_off = [i[k] for k in falling]
        turn_on = [i[k + 1] for k in rising]
        zvs = [_sign_after(i, k + 1, threshold, horizon) for k in rising]
        notes.append("Switching instants taken from gate threshold crossings")
    else:
        step = 0.1 * peak
        falling = [k for k in range(len(i) - 1) if i[k] > step and abs(i[k + 1]) <= threshold]
        rising = [k for k in range(len(i) - 1) if abs(i[k]) <= threshold and abs(i[k + 1]) > step]
        turn_off = [i[k] for k in falling]
        turn_on = [i[k + 1] for k in rising]
        zvs = [_sign_after(i, k + 1, threshold, horizon) for k in rising]
        notes.append(
            "Switching instants inferred from current steps; supply the gate signal for exact"
            " instants and dead-time intervals"
        )
    if any(flag is None for flag in zvs):
        notes.append("ZVS condition undetermined for at least one turn-on event (current ~0)")
        zvs_flags = ()
    else:
        zvs_flags = tuple(bool(z) for z in zvs)
    blocking = ()
    v_ds_max = None
    if waveform.drain_source_voltage is not None:
        v = waveform.drain_source_voltage
        v_ds_max = max(v)
        # Sample the blocking voltage one percent of a period after the edge, past the ramp.
        delay = 0.01 / switching_frequency
        blocking = tuple(v[min(len(v) - 1, bisect_left(t, t[k] + delay))] for k in falling)
    return SwitchStress(
        switch_id=switch_id,
        bridge=bridge,
        source="sampled_waveform",
        periods=periods,
        switching_frequency=switching_frequency,
        current_rms=rms,
        current_avg=avg,
        current_peak_forward=peak_fwd,
        current_peak_reverse=peak_rev,
        conduction_fraction=conduction_fraction,
        forward_charge_per_cycle=forward_charge,
        reverse_charge_per_cycle=min(reverse_charge, 0.0),
        turn_off_currents=tuple(turn_off),
        turn_on_currents=tuple(turn_on),
        zvs_turn_on=zvs_flags,
        blocking_voltages=blocking,
        v_ds_max=v_ds_max,
        waveform=waveform,
        dataset_sha256=dataset_sha256,
        notes=tuple(notes),
    )


def load_hdf5_switch_waveform(
    path: str | Path, switch_id: str, *, window: tuple[float, float] | None = None
) -> tuple[SwitchWaveform, str | None]:
    """Read ``/time`` and the switch channels of an AIPE waveform dataset (needs h5py)."""
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("Reading HDF5 waveforms requires the optional h5py package") from exc
    with h5py.File(Path(path), "r") as handle:
        time = [float(x) for x in handle["/time"][:]]
        channels = handle["/channels"]

        def channel(name):
            return [float(x) for x in channels[name][:]] if name in channels else None

        current = channel(f"i_{switch_id}")
        if current is None:
            raise ValueError(f"Dataset has no channel i_{switch_id}")
        gate = channel(f"g_{switch_id}")
        v_ds = channel(f"v_ds_{switch_id}")
        digest = handle.attrs.get("sha256")
        digest = digest.decode() if isinstance(digest, bytes) else digest
    if window is not None:
        t0, t1 = window
        keep = [k for k, x in enumerate(time) if t0 <= x <= t1]
        time = [time[k] for k in keep]
        current = [current[k] for k in keep]
        gate = [gate[k] for k in keep] if gate is not None else None
        v_ds = [v_ds[k] for k in keep] if v_ds is not None else None
    return (
        SwitchWaveform(
            time=tuple(time),
            current=tuple(current),
            gate=tuple(gate) if gate is not None else None,
            drain_source_voltage=tuple(v_ds) if v_ds is not None else None,
        ),
        digest if isinstance(digest, str) else None,
    )
