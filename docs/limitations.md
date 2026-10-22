# Limitations and roadmap

- Source coverage is not engineering operating coverage. 900/1000 °C points remain in 742 curves; 24 curves
  in six devices have duplicate temperature coordinates. Reports expose both; interpolation rejects duplicate
  coordinates.
- PLECS adapters cover this corpus's tabulated MOSFET-with-diode dialect, including 90 custom tables. Export
  requires explicit adapter bindings. Unknown custom-table semantics are rejected. No formula execution or
  simulator/XSD validation is claimed.
- Ratings, capacitance, gate charge, SOA, reliability and internal module connectivity remain unknown in the
  canonical corpus; unreviewed datasheet candidates carry some of them for 19 parts. Synthetic fixtures
  exercise other technology schemas only.
- 1D and N-D linear interpolation, Cauer/Foster thermal responses and a DAB switch loss evaluator are
  implemented on manufacturer model data; model fitting and generic waveform processing remain extension
  contracts. No measured evidence backs any loss.
- JSON persistence has atomic files and an exclusive writer lock. No distributed database, cloud backend or
  authorization engine is included.
- No PDF digitization, SPICE parsing, laboratory control, lifetime prediction, distributor APIs or AI
  missing-data reconstruction.

## Roadmap

Future iterations should resolve source-axis ambiguities, add reviewed operating envelopes and
multidimensional evaluations, validate exports in PLECS, implement DPT processing and artifact backends, and
add measured/rating/capacitance datasets. See [architecture](architecture.md),
[DAB guide](dab-loss-screening.md), [audit](audit.md), [deliverables](refactor-report.md),
[breaking changes](../CHANGELOG.md) and [licensing notes](../LICENSING.md).
