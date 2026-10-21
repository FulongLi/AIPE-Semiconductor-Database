# DAB loss evaluation, device screening and measurement requests (3.1.0)

Version 3.1.0 turns the `LossEvaluator` contract into a working evaluator for one
switch position of a dual-active-bridge (DAB) converter, adds N-dimensional tensor
interpolation with an explicit operating-envelope policy, Cauer/Foster thermal
services with an electro-thermal fixed point, reviewable datasheet candidate records,
an evidence-tiered device screening and prioritised laboratory measurement requests.
Everything consumes **actual converter stress** (the AIPE waveform summary or a sampled
waveform) and **canonical or candidate records**; nothing is estimated silently. The
package now runs on Python 3.10 (a `StrEnum` backport in `schema/enums.py`).

## Inputs

| Input | Source | Notes |
| --- | --- | --- |
| Switch stress | `aipe-dab-waveform-summary/0.1` JSON (`switches[]`, `window`, `valid`) or a sampled one-period (integer-period) waveform `(t, i[, gate, v_ds])`, e.g. from the HDF5 dataset | Positive current is drain-to-source. Summaries marked `valid: false` or without steady state are rejected. |
| Device record | Canonical device (`data/canonical`) with `voltage_drop`, `Eon`/`Eoff` tensors, Cauer network and PLECS bindings | Candidate records (`data/candidates/records`) supply ratings and datasheet points. |
| Operating point | `OperatingCondition` with `junction_temperature` (K), `dc_bus_voltage` (V), `switching_frequency` (Hz), optional gate resistances (Ohm) and gate voltages (V) | `services.loss.dab.operating_point(...)` builds it. ZVS may be stated as the extension `zvs_turn_on`. |

## N-D interpolation and the envelope policy

`services.interpolation.NDInterpolator` / `PreparedTensor` evaluate dense `Curve`
tensors multilinearly over all named axes. `EnvelopePolicy` makes the evidence
envelope explicit:

- junction-temperature source points at or above 773.15 K (500 degC) are PLECS
  extrapolation guard rows and are dropped (`guard_rows_dropped:junction_temperature`);
- coordinates outside the remaining envelope raise unless
  `allow_extrapolation=True`; extrapolated results carry `extrapolated:<axis>` flags and
  the `extrapolated` origin (`linear` edge-segment or `hold_nearest` method);
- duplicate axis coordinates and stale evidence are rejected, as in Phase 1.

The one-dimensional `Interpolator` is unchanged.

## DAB switch-position losses

`services.loss.dab.DABLossEvaluator(stress, policy=..., reverse_conduction=...)`
implements `LossEvaluator.evaluate(device=..., operating_point=...)` and returns
`ScalarRecord`s in W with `physics_derived` origin, `derived` lifecycle, recipe
`dab-switch-loss 1.0` and dependencies on every tensor ID used plus the waveform
dataset SHA-256. `evaluate_detailed()` adds the breakdown, per-event energies,
warnings and the `coverage` list.

| Term | Method |
| --- | --- |
| Conduction, waveform path | `mean(v(Tj, i(t)) * i(t))` over the window. Positive current uses the gate-on `voltage_drop` tensor. Negative current follows the reverse policy: `gate_aware` (default) uses the gate-on tensor while the gate is on (synchronous rectification) and the gate-off third-quadrant tensor during dead time; `body_diode` sends all negative current through the third-quadrant tensor; `channel` uses the gate-on tensor throughout. Forward and reverse parts are reported separately. |
| Conduction, summary path | `v(Tj, I_rms)/I_rms * I_rms^2` (secant on-resistance at the RMS current); reverse intervals assumed channel-conducted; flagged `method:rms_equivalent_resistance`. The `body_diode` policy needs a waveform. |
| Turn-off | `f_sw * sum_k Eoff(Tj, Vdc, I_off,k) * k_Rg / periods` over the turn-off events of the window. `k_Rg` comes from a gate-resistance tensor axis (4-D custom tables) or from the stored PLECS `Table and formula` expression evaluated by a restricted grammar (`plecs_formula.py`; numbers, `E`, one `Rg` variable, `+ - * / ^`, parentheses; `lookup()` and anything else rejected). Requested gate resistances outside the model's `MinValue..MaxValue` follow the extrapolation policy. Turn-off at reverse or ~zero current is soft (0 J). |
| Turn-on | 0 J for events whose ZVS current condition holds (summary `zvs_current_condition.per_event`, waveform sign after the edge, operating-point extension or constructor override); otherwise `Eon(Tj, Vdc, I_on) * k_Rg`. |

The `coverage` list names every quantity that was unavailable, approximated,
interpolated or not evaluated: `coss`/`Eoss`/`qoss` (no charge-based ZVS check),
`vds_max`/`id_max`/`tj_max` (no ratings in the Wolfspeed corpus), `rds_on_vs_tj`
(follows the tensor), `gate_voltage_dependence`, `rg_dependence_Eoff` (formula or
unavailable), `reverse_recovery`, `dead_time_body_diode_conduction`,
`conduction_waveform_integral` (summary path), `measured_evidence` (all tensors are
manufacturer model data) and the bracketing source points of every interpolation.

### Actual numbers, run `dab-l1-nominal-ic` (800 V -> 400 V, 100 kHz, SPS, 10 kW)

Canonical records `wolfspeed_c3m0075120k` (TI primary device) and
`wolfspeed_c3m0030090k` (TI secondary device) exist, so no substitute device was needed.
Tj = 398.15 K, Rg 2 Ohm / 2 Ohm, +15 V / -4 V (2.5 Ohm for the 090K, see below):

| Switch / device | Path | Conduction W | Turn-off W | Turn-on W | Total W |
| --- | --- | --- | --- | --- | --- |
| S1 / C3M0075120K | summary metrics | 10.40 | 5.95 | 0 (ZVS) | 16.35 |
| S1 / C3M0075120K | HDF5 waveform, `gate_aware` | 10.56 (10.34 forward + 0.22 reverse) | 5.95 | 0 | 16.51 |
| S1 / C3M0075120K | HDF5 waveform, `body_diode` | 11.31 | 5.95 | 0 | 17.26 |
| S5 / C3M0030090K, Rg 2.5 Ohm | summary metrics | 13.92 | 5.79 | 0 | 19.71 |
| S5 / C3M0030090K, Rg 2.5 Ohm | HDF5 waveform, `gate_aware` | 13.23 (0.45 forward + 12.78 reverse) | 5.80 | 0 | 19.03 |
| S5 / C3M0030090K, Rg 2.5 Ohm | HDF5 waveform, `body_diode` | 65.51 | 5.80 | 0 | 71.31 |

Eoff per event: 59.5 uJ at 14.26 A / 800 V / 125 degC (table value scaled by the PLECS
factor 1.1234 at Rg,off 2 Ohm) for the 075120K; 57.9 uJ at 32.5 A / 400 V for the
030090K. The 030090K PLECS model is defined for Rg >= 2.5 Ohm; TI's 2 Ohm is outside
the model range and is evaluated only with `--allow-extrapolation` (turn-off 5.00 W,
flagged). The `body_diode` policy illustrates why `gate_aware` is the default: the
secondary bridge conducts almost entirely in reverse (synchronous rectification) and
would otherwise be charged with ~4 V body-diode drops.

Electro-thermal fixed point for S1 with Rth(c-s) 0.1 K/W, Rth(s-a) 0.5 K/W, 40 degC
ambient: Tj = 335.95 K (62.8 degC) at 13.81 W after 4 iterations (|dTj| < 0.05 K).

## Thermal services

`services.thermal.ThermalEvaluator` adds `foster_terms`, `foster_equivalent` (exact
Cauer -> Foster via the eigen-decomposition of the symmetric ladder matrix, pure
Python Jacobi rotations, DC resistance preserved), `step_response(network, times)`
(Zth(t) in K/W) and `junction_temperature(network, loss, rth_case_to_sink=...,
sink_temperature=..., time=None)`. `electro_thermal_fixed_point(loss_at, ...)` iterates
Tj -> loss(Tj) -> T_sink + loss * Rth with damping, an explicit criterion, a limit for
thermal runaway and an iteration record; evidence-envelope violations end the
iteration with `converged=False` instead of extrapolating. For C3M0075120K the Cauer
network (sum R 1.0512 K/W) converts to Foster terms (0.0136 K/W, 6.9 us), (0.0371,
68 us), (0.515, 2.7 ms), (0.485, 169 ms), matching a SciPy `expm` reference to 1e-14.

## Candidate records

`aipe_devices.importers.datasheet.DatasheetImporter` turns a structured transcription
(`aipe-datasheet-transcription/0.1`, YAML or JSON) into schema-valid, unreviewed
candidate records plus a review dossier. See `data/candidates/README.md` for the rules
(as-printed values, SI conversion by the explicit registry, third-quadrant sign
convention, `absent` lists, canonical links through `urn:aipe:semiconductor:...`,
no PDF or model files). `data/candidates/sic-dab-shortlist-2026-10-21.yaml` transcribes
the 17-device shortlist and the two TI reference-design parts (TI-cited values flagged
`basis:third_party_cited`). Rebuild with `python scripts/generate_candidates.py` or
`aipe-devices import-candidates <transcription> --output <dir>`.

## Screening

`services.selection.DABScreening(summary, ScreeningSettings(...)).screen(pool)` ranks
the pool per bridge (primary: port-1 voltage, secondary: port-2 voltage) using the
worst-case switch of each bridge:

- electrical suitability: `V_peak / VDS_rating <= derating_limit` (0.70 default) is a
  hard gate; the continuous current rating closest to TC 100 degC is compared with
  I_rms and the peak current;
- losses at the evaluation temperature (398.15 K default): tier A devices use
  `DABLossEvaluator` on canonical tensors; tier B devices use datasheet points,
  `Rds(on)(Tj) * I_rms^2` with linear Tj interpolation between printed temperatures
  (nearest printed value otherwise, flagged) and `Eoff * (V/V_ds) * (I/I_ds)` scaled
  linearly from the printed test point without gate-resistance scaling, every
  approximation flagged;
- junction-temperature headroom: `T_amb + P * (Rth_jc + Rth_cs + Rth_sa)` with the
  user-supplied case-to-sink and sink-to-ambient resistances, plus the electro-thermal
  fixed point when loss(Tj) is available; devices without headroom to the design limit
  are excluded;
- data confidence: weighted score over ratings, conduction, switching, thermal,
  capacitance and (always absent) measured evidence, and a tier
  (`A_canonical_tensors`, `B_datasheet_points`, `C_insufficient`). Ranking sorts by tier
  first, then total loss; tier C is never ranked.

Result for the nominal run with Rth(c-s) 0.1 K/W and Rth(s-a) 0.5 K/W: primary bridge
tier A: CBB021M12FM3 (7.0 W per position), C4MS047120K (8.5 W), C3M0040120K (11.0 W),
C3M0075120K (16.4 W); tier B: SCT4036KR, NXH020P120MNF1, IMBG120R040M2H,
MSC040SMA120B4, NTH4L022N120M3S, IMZA120R040M2H, SCT040W120G3-4; all 650/700/750/900 V
parts excluded by derating; FF45MR12W1M1_B11 unranked (datasheet not retrieved).
Secondary bridge tier A: CBB021M12FM3 (15.7 W), C3M0025065K (16.2 W), C3M0030090K
(19.7 W), C3M0040120K, C4MS047120K; C3M0075120K excluded (54 W, no headroom);
IMZA65R027M1H unranked (no Eon/Eoff in its datasheet).

## Measurement requests

`services.measurement_requests.generate_dab_measurement_requests(device, result, ...)`
builds a `MeasurementRequest` (the existing partner shape, all items `draft=True`) with
eight items: static channel I-V, Rds(on) vs Tj, double-pulse Eon/Eoff vs voltage,
current, Rg(on/off) and Tj, reverse conduction with the gate off and on, Coss/Eoss/Qoss,
Zth(j-c) and package/interface thermal resistances. Sweeps are centred on the actual
stress (I_rms, peak and turn-off currents, bus voltage, requested Rg). Each item carries
the engineering question, an uncertainty target and a priority
`score = expected_design_benefit * current_uncertainty`, where the benefit follows the
loss share (or thermal headroom) and the uncertainty follows the coverage status of the
backing evidence (model point 0.35 ... unavailable 1.0). Safety statements are part of
the output; nothing is executed.

## CLI

```bash
aipe-devices dab-losses --device wolfspeed_c3m0075120k --summary runs/dab-l1-nominal-ic/summary.json \
  --switch S1 --tj 398.15 --vdc 800 --fsw 100e3 --rg-on 2 --rg-off 2 --vgs-on 15 --vgs-off -4 \
  --rth-cs 0.1 --rth-sa 0.5 [--waveforms runs/dab-l1-nominal-ic/waveforms.h5] [--reverse-policy gate_aware]
aipe-devices dab-screen --summary runs/dab-l1-nominal-ic/summary.json --rth-cs 0.1 --rth-sa 0.5 \
  [--candidates data/candidates/records] [--tj 398.15] [--derating 0.7] [--output screen.json]
aipe-devices measurement-requests --device wolfspeed_c3m0075120k --summary ... --switch S1 \
  --tj 398.15 --vdc 800 --fsw 100e3 --rg-on 2 --rg-off 2 --rth-cs 0.1 --rth-sa 0.5
aipe-devices import-candidates data/candidates/sic-dab-shortlist-2026-10-21.yaml --output data/candidates/records
```

All commands print JSON; `--output` also writes it atomically. Reading HDF5 needs the
`waveforms` extra (h5py); YAML transcriptions need the `candidates` extra (pyyaml).

## Limitations

- All loss evidence is manufacturer model or datasheet data; the `measured_evidence`
  coverage entry is always unavailable until laboratory data are imported.
- The summary path cannot separate forward and reverse conduction or dead-time
  body-diode intervals; use the HDF5 waveform path for those.
- Gate-voltage dependence is not represented by the corpus tensors; the requested
  +15 V / -4 V drive is recorded, not modelled.
- No Coss/Eoss/Qoss records exist, so ZVS is accepted on the current condition only and
  turn-on loss under ZVS is zero by assumption.
- Datasheet-point scaling (tier B) is linear in V and I and ignores Rg; it is a
  flagged estimate for ranking within its tier, not a loss prediction.
- Ratings for Wolfspeed canonical devices come from candidate records (datasheet or
  TI-cited); the legacy V2 `vds_max` fields are inferred values and are not used.
- The screening evaluates each bridge's worst-case switch and treats module values as
  per switch position; thermal coupling between positions is not modelled.
