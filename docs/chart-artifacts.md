# Custom Python chart artifacts

Custom `run_code` charts now follow an explicit versioned artifact contract from
sandbox capture through agent/API responses and chat metadata to Saved Analyses,
past chats, and the center Result workspace. Figure payloads are stored as files,
not base64 strings inside chat records.

## Storage and delivery

Each artifact has a unique UUID and is saved under
`workspace/projects/<project-id>/charts/`:

- `<artifact-id>.artifact.json`: manifest and internal filenames.
- `<artifact-id>-figure.json`: structured Plotly figure data, when captured.
- `<artifact-id>-download.html`: standalone HTML with Plotly.js bundled inline.
- `<artifact-id>-download.png`: PNG image, for Matplotlib output.

Public metadata contains `version`, `id`, `kind`, `title`, `status`, MIME type,
optional dimensions, reason, and project-scoped figure/image/download URLs.
Plotly and PNG are never interchangeable. HTML is returned only as an attachment
with `nosniff` and a sandbox CSP. The app never embeds generated HTML or injects
its scripts. Plotly JSON is drawn through the existing locally bundled renderer.

The sandbox captures Plotly figures in scope and figures passed to `show()` or
`write_html()`. It captures active Matplotlib figures and saved PNGs, including
closed figures saved inside the execution directory. Runs execute in their
own temporary working directory. Figures within one run and graphs from later
runs receive distinct persistent filenames. Temporary files are cleaned after
capture. Python exceptions never produce successful result artifacts.

Successful artifacts remain available if a later model call fails while preparing
an explanation. Original questions and `run_code` table/join/code provenance are
retained in saved metadata. Chart-only outputs can open directly in Result; tables
continue to use their existing mounted sorter/paginator.

## Presentation

Generated plots receive opaque surfaces, readable fonts, axis/grid defaults,
responsive width, and currency/month formatting where the axis title supplies
units. Explicit trace values, series colors, ranges, logarithmic scales,
annotations, frames, and chart-specific trace settings are retained. Generic
Plotly templates are normalized to the workspace theme. The title is shown once
as an accessible heading outside the zoom toolbar.

The container observes width changes, including sidebar resizing and chat
collapse. Long series names wrap on narrow screens. Dense categorical plots use
horizontal scrolling with a notice that all categories remain included. No Top N
or silent aggregation is applied to generated figures. PNGs keep their aspect
ratio; narrow screens offer scrolling and full-size viewing rather than stretching
or pretending the image is interactive.

Empty figures, unsupported external-resource plots, and JSON capture failures
show explanations with downloads where captured. Geographic plots requiring
external geometry/images are not fetched or rendered in Result. Their standalone
exports may still require those external resources even though Plotly.js is
bundled. Older untyped `chart_base64` records show a regeneration message rather
than treating HTML bytes as an image.

## Verification

No live model calls were used. Controlled tool/final-answer responses exercise
the real Python subprocess, agent, shared API processing, database persistence,
artifact file endpoints, and browser rendering.

```bash
docker --context desktop-linux compose exec -T backend python -m unittest discover -s tests
docker --context desktop-linux compose exec -T frontend npm test
docker --context desktop-linux compose exec -T frontend npm run build
# Generate temporary persisted examples for browser inspection:
docker --context desktop-linux compose exec -T -e PYTHONPATH=/app/server backend python tests/generate_artifact_examples.py
# Run separately from builds:
node client/tests/browser-artifacts.mjs
```

The generator creates a project called `Artifact delivery verification`; remove
that project after checking. The browser script reads its real saved artifacts,
checks downloads and provenance, opens from Saved Analyses and past chats after
reload, and simulates delivery of one captured chat reply. It checks desktop and
390px layouts, pane resize/chat collapse, and offline interaction with an already
loaded figure. It records screenshots under `/tmp/v1-artifact-visuals/`.

Verified examples: multi-series line with annotation and negative revenue,
1,500-point scatter, histogram, box, heatmap, donut, 25 dense categories with long
labels, Matplotlib PNG, empty figure, unsupported geographic chart, and a forced
JSON-capture failure with a retained HTML download. Real sandbox regressions
verify two consecutive identical graphs remain independently accessible.

Remaining limits: browser inspection uses Chrome; full screen-reader testing,
large 3D/WebGL scenes, arbitrary external-resource figures, and extremely large
artifacts have not been audited. PNG output is inherently static. The existing
sandbox execution time/memory limits still apply. Original arbitrary HTML is
never promoted into an executable in-app preview.
