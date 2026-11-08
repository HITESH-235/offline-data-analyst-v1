# Northwind correlation result consistency

## Root causes

The captured answer `9fb53a73-c13f-4a37-95eb-72186490ceeb` used the SIMPLE correlation tool. Its prompt listed only the visualization blueprint tool's old chart types, without describing Open result's separate heatmap renderer. The model therefore claimed heatmaps were unavailable despite the frontend correctly rendering the supplied matrix. The agent returned the model's interpretation unchecked, including an invalid claim of statistical independence.

The correlation tool accepted only a method and computed every numeric column, including identifiers. The analysis engine then fell through to packaging the unchanged source dataframe as the structured result. The frontend excluded identifiers when displaying the heatmap, so Chart looked like a three-measure analysis while Table exposed 609,283 raw rows.

## Changes

Correlation accepts and validates explicit measure names and method. The agent resolves exact measure mentions from the question in their requested order and records the effective parameters in calculation provenance. Identifiers are excluded from default measure selection, but can be explicitly requested.

The engine returns a matrix table immediately, with `analysis_kind: correlation`, three labelled matrix rows, shared correlation metadata and a separate `source_observation_count`. Pairwise finite-observation counts and missing-value policy are also preserved. Undefined coefficients remain null instead of being fabricated as zero. Invalid columns, methods and insufficient input fail explicitly.

Capability instructions now distinguish the blueprint tool from Open result's renderer. A correlation result needs no additional visualization call. The final correlation narrative is generated from verified result coefficients and states that near-zero Pearson correlation does not establish independence or rule out nonlinear relationships.

Table, heatmap labels and narrative use four-decimal display precision, retaining full coefficients in the payload and table cell titles. Small heatmaps (up to eight measures) have visible coefficient labels; both axes follow the matrix's measure order with rows top-to-bottom matching Table. Explicitly requested identifiers are retained in validated matrices. Matrix cells are not treated as raw observations for other chart choices.

## Northwind comparison

Actual backend dataset: `/app/datasets/northwind.db`, table `Order Details`, 609,283 source observations.

| Measure | UnitPrice | Quantity | Discount |
|---|---:|---:|---:|
| UnitPrice | 1.0000 | 0.0006 | -0.0031 |
| Quantity | 0.0006 | 1.0000 | 0.0045 |
| Discount | -0.0031 | 0.0045 | 1.0000 |

A test independently calculates Pearson coefficients from centered NumPy dot products and checks all nine application coefficients within absolute tolerance `1e-12`. The captured backend result is stored in `client/tests/fixtures/northwind-correlation.json`; frontend tests verify that its table values, heatmap data, labels, requested measure order and narrative agree.

The existing saved response was repaired to use the compact matrix and corrected narrative, preserving its original question, source and calculation steps. All 34 chat messages were preserved. Backup: `/tmp/correlation-result-backup-5z5wvicc/original.db`. The running saved-analysis endpoint confirms it restores the corrected matrix and source.

## Checks

- 6 correlation tests passed, including the real Northwind calculation, malformed arguments, missing/constant values, pair counts, corrected interpretation and API/Saved Analyses/past-chat restoration using mocked model responses.
- 37 related backend tests passed: summary results, provider failures, date filters/monthly revenue and chart population consistency.
- Frontend `npm test` passed (both test files, including captured correlation checks).
- Production build passed in the existing frontend container. The host attempt could not find Vite; the container has the project's installed build dependencies.
- `git diff --check` passed.
- No live model requests or browser checks were performed. Coefficient-label appearance and narrow-layout visual quality remain for user browser testing.

Refresh the app, reopen the latest correlation analysis and confirm Table shows three measure rows, Chart shows the same 3×3 coefficients, source observations are labelled 609,283, axes share the requested order, and calculation details retain Order Details and the effective correlation parameters.

## Follow-up: custom Python bypass

A later fresh response, `7782fe1d-59e4-42cd-b8b1-9db2e2a8027d`, reproduced a missing path: the planner chose COMPLEX, Python called `df[cols].corr()` and Seaborn generated a PNG, but the sandbox returned only chart artifacts. The preceding fix handled only the built-in correlation tool. The PNG also used automatic color limits rather than a fixed correlation range.

The sandbox now captures actual DataFrame.corr outputs and validates the requested column order, method, observation count and coefficients against the resolved source dataframe. Missing/mismatched matrices fail before artifact persistence. Python correlation responses carry the same structured result contract as built-in correlations, alongside their original artifacts and code provenance. Matrix-only Python output also opens in Table and Chart without needing a PNG. Saved and historical chat responses retain the matrix and source even without a captured image.

Result workspace gives a validated correlation matrix priority over Python artifacts. Both paths therefore use the same local heatmap renderer, with a diverging scale explicitly fixed at -1 and +1, neutral at zero (`zmid: 0`, `zauto: false`). Small heatmaps retain coefficient labels; axes retain the same measure order. Chat and library cards identify these results as a matrix and heatmap rather than PNG-only output. Original Python artifacts remain preserved, but are not the primary correlation display.

Fresh controlled responses were tested through actual sandbox execution for Seaborn PNG, Plotly and matrix-only code, with restoration through Saved Analyses and chat history. The relevant backend run passed 29 tests; frontend tests and production build passed. Browser testing remains with the user.

Fresh built-in response `5c1d2c6c-078b-4df9-a3b4-f255e70d4201` completed in 22.56 seconds and returned the correct 3×3 matrix and 609,283 source observations. All coefficients and displayed narrative values matched an independent centered dot-product calculation from Northwind, within absolute tolerance 1e-12. This was a newly generated response, not a saved-record repair.

Fresh live custom-Python response `fff8790c-777b-4db7-b18c-942acd824bba` completed in 45.04 seconds with COMPLEX routing, an actual `run_code` call using `df[['UnitPrice','Quantity','Discount']].corr(method='pearson')`, and a Plotly artifact. The first generated program had an unterminated string and failed validation; the model corrected it on retry. The final response type was `table` and included the validated matrix alongside the artifact. All nine coefficients, matrix table and narrative matched independent Northwind calculations within absolute tolerance 1e-12. Both fresh live responses restore their matrices and source metadata through the running saved-analysis and past-chat endpoints. No saved records were repaired for these follow-up checks.
