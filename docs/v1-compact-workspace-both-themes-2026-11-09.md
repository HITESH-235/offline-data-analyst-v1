# Compact V1 workspace and matched light/dark themes

This update supersedes the earlier dark-only palette and density notes.

## Changes

- Chat's Open result button is now a compact two-line row with a small table icon, label and arrow. Sources truncate inside the available width; row/matrix/export counts remain alongside or wrap when necessary. The complete source text remains in the accessible button text and title. The row is at least 44px tall, with a thin border, hover state and keyboard focus ring.
- The result workspace uses a compact, wrapping question and a brief status line with an icon and text. Detailed validation messages are retained in a closed-by-default Validation details disclosure. Calculation provenance and export controls remain available.
- Table/Chart buttons and result dimensions share one wrapping toolbar. The selected output's source appears once next to that toolbar, with full wrapping text and source observation count where available. The repeated source banners above the workspace and chart were removed.
- Chart controls use an adaptive grid with shrinking native selects and full field names in their options; selected measure/category names also have titles. Chart guidance is expandable. Chart titles, footnotes, omitted-row information and row-meaning controls remain available. Table pagination, result limits, chart Top N choices/ranking, calculation outputs and chart selection state are unchanged.
- Body text is 13px, secondary text generally 12px, workspace headings 20–21px and question text 14px. Main controls use a 32px minimum height; the theme toggle is 36px. Workspace, chat and saved-library padding is reduced. Result tables grow with their paginated content rather than an extra viewport-height cap. No CSS zoom or global scaling was introduced.
- Both modes use the requested solid black/blue/orange and light/blue/orange palettes. Light navigation is now light as well. Dark main background is true black. Blue is primary, orange accents Saved Analyses and secondary emphasis, success remains green and failure/delete remains red. A lighter blue is retained for dark link text to clear AA contrast over navy selections.
- Shared Plotly theme tokens supply coordinated categorical colors, legible labels/tooltips and subtle grids. Existing data, custom explicit chart colors, numeric color scales, marker/dash distinctions and saved charts remain intact.
- No wallpaper reference was present in the loaded app styles. Root, navigation and work surfaces now explicitly use solid opaque backgrounds with background images disabled. The unused starter App.css is not imported; it was left untouched.

## Files changed in this update

- `client/src/theme.css` — both palettes and shared interaction states.
- `client/src/index.css` — compact sizing, wrapping, responsive grid, result link and opaque surfaces.
- `client/index.html` — matching light/dark background before app mount; preference bootstrap unchanged.
- `client/src/components/chat/ChatPanel.jsx` — compact result link and chat-feed class.
- `client/src/components/dataset/DatasetViewer.jsx` — remove repeated source banner.
- `client/src/components/dataset/ResultWorkspace.jsx` — brief status, validation disclosure and one source location.
- `client/src/components/dataset/ResultChart.jsx` — chart guidance disclosure, field titles and remove repeated source.
- This report.

Backend code, request deadlines, analysis calculations, completion decisions, dataset browsing logic, saved data and unrelated uncommitted changes were not edited in this update. No live analysis/model calls, commits or pushes were made.

## Verification

- All **six frontend test files** passed, including existing theme-preference, chart-value/Top N, semantic-status, saved-result package and request-watchdog checks.
- All **164 token contrast cases** passed. Minimum tested text contrast: light **4.94:1**, dark **5.03:1**. Minimum tested control/chart contrast: light **3.27:1**, dark **3.59:1**.
- A Vite SSR rendering smoke check passed for complete, incomplete and legacy snapshots, including long questions/source names, unchanged result values, a single source occurrence and retained validation detail. This verifies markup/content, not browser layout.
- Production Vite build passed in the existing frontend container (2,050 modules).
- `git diff --check` passed.

## Visual verification left to the user

No browser inspection connector or browser executable was available. **No viewport or browser zoom level was visually verified.**

Suggested checks at `http://localhost:3001`:

1. Use a 1440 × 900 browser window at 100% zoom, then 110%. Repeat in light and dark mode. Reload after toggling to confirm the saved preference. The CSS viewport will shrink as browser zoom increases; allow responsive wrapping to take effect.
2. Open a saved result with a long question and multiple/long source names. Confirm the source is shown once by the toolbar, the question wraps, and validation details can be expanded. Switch Table/Chart and calculation outputs; inspect pagination, sorting and result dimensions.
3. Inspect bar/line and multi-output charts. Confirm all chart selectors, long option names, the unchanged Top 5/10/20 choices, guidance disclosure, tooltips and keyboard chart inspection remain usable. Ensure no controls overlap at 110% zoom.
4. In chat, confirm Open result is a small icon/label/arrow row, long sources truncate without widening the panel, counts wrap if necessary, and Enter/Space activates the focused button.
5. Tab through navigation, inputs, tabs and delete controls; check focus, selected, hover and disabled states. Confirm success/error states retain text and icons in addition to color.
6. Also check a 1280 × 800 window and a narrow 390 × 844 viewport. Confirm navigation collapse, responsive control grids and horizontal table scrolling remain usable, with no wallpaper showing through work surfaces.
