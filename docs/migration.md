# Migration and reproducibility

The official corpus was rebuilt from all **163 original XML files**: 119 discrete,
44 module, 742 curves and 90 four-dimensional custom tables. All 164 raw files
(including the manufacturer PDF) match pre-refactor checksums in
`data/raw/manifest.json`. All 326 legacy JSON files were moved unchanged.

No source point, formula, comment, variable, custom table or thermal network was
removed. `migration-report.json` records each source checksum and issue. There are
742 high-temperature warnings and 24 duplicate-axis warnings across six devices,
with no validation errors. Duplicate 200 °C coordinates remain intact and block interpolation.

```bash
aipe-devices import-wolfspeed data/raw/wolfspeed data/canonical --report docs/migration-report.json
aipe-devices migrate-legacy v1 legacy/v1 /tmp/aipe-v1-review
aipe-devices migrate-legacy v2 legacy/v2 /tmp/aipe-v2-review
```

The corpus importer verifies existing identical objects; changed records raise.
Classification comes from the known catalogue. Generic PLECS imports default unknown
when material/integration is not explicitly supplied.

V1 migration maps its PLECS-shaped fields through the adapter and references original
legacy bytes. V1 lost namespaces/custom tables. Unresolved lookup expressions block
export with an instruction to reimport XML; missing tables are not fabricated.

V2 migration preserves available table points, normalizes declared units and marks
coverage partial. Ratings/static values stay inferred/derived with legacy dependencies.
Injected gate voltage, statistics and guessed identity/package fields are not asserted;
their original representation remains in the linked artifact. Formula/variable information
also remains in that artifact. No lost four-dimensional data is reconstructed.

Use separate repositories for alternative legacy imports. IDs derived from manufacturer
and part are catalogue convenience keys; distinct revisions/samples can use new IDs.

Every XML has a semantic roundtrip test, including all custom-table values, scale,
temperature conversion, conduction, RC elements, formulas, variables and comments.
All 326 legacy documents run migration validation. Independent C2M0025120D goldens:

- Eon at 25 °C / 800 V / 12.56 A: 0.371 mJ.
- Eoff at the same table point: 0.07008 mJ.
- Conduction at 25 °C / 1.727 A: 0.1024 V.
- Sum of Cauer thermal resistances: 0.2688 K/W.

These are manufacturer-model values, not new measurements or a gate-drive claim.
No PLECS simulator or external XSD acceptance test has been run.
