# V1 black, blue and orange dark theme

Dark-mode tokens in `client/src/theme.css` now use the requested near-black workspace (`#080B10`), dark chrome (`#0D121B`), panels (`#121B29`), quiet borders (`#26364A`), bright blue actions (`#409CFF`), navy selection (`#17345C`), orange emphasis (`#FF9B45`), primary text (`#F3F6FC`) and secondary text (`#A7B6CA`). Link text uses a derived lighter blue (`#58A8FF`) so it clears AA contrast on navy selected backgrounds. Primary buttons use dark text. No gradients or glow were added.

Navigation, chat, inputs, tables, result panels and tooltips inherit these tokens. Saved Analyses uses small orange icons, badges and hover cues. Success remains green and failure/delete remains red, with existing labels and icons. Interactive control borders use a separate stronger token; decorative dividers stay subtle. Existing selected indicators and keyboard focus rings remain visible, with distinct hover, pressed and disabled treatments.

Plotly's existing shared theme adapter automatically receives the new surfaces, labels, gridlines and categorical palette: blue, orange, teal, lavender and pale gold. Existing status overrides retain green/red meanings; existing line markers/dashes distinguish series beyond color. Numeric color scales, observations, saved chart data, requested custom colors and view state are preserved. Static saved chart images retain their original rendering and neutral image frame.

The light-mode token values and saved-preference bootstrap are unchanged. The initial dark page background was updated to match the workspace before React mounts. Layout, analysis logic, datasets, saved results and unrelated uncommitted work were preserved. No browser testing, model calls, commit or push was performed.

Verified:

- All six frontend test files passed, including theme preference persistence, chart value/style preservation, semantic status colors and bar-label readability.
- All 164 existing text/control/chart contrast cases passed. Dark text pairs have a minimum of **5.03:1**, and dark non-text control/chart pairs a minimum of **3.54:1**. Primary button text contrast is **6.96:1**. Light-mode checks also passed.
- The contrast fixture now checks the actual interactive chrome border token rather than decorative dividers.
- Production Vite build passed in `offline-analyst-frontend` (2,050 modules).
- `git diff --check` passed. Existing light token values and theme initialization script were compared with their pre-edit copies and are unchanged.

These checks validate token combinations and chart transformations; visual browser verification remains with the user.

Browser checklist:

1. Open V1 at `http://localhost:3001`, select dark mode, reload, and confirm the preference persists without a flash of the former dark background.
2. Inspect navigation, chat/composer, inputs, data tables, result tabs and Saved Analyses. Confirm quiet dark surfaces, blue primary actions/selections and limited orange library emphasis.
3. Tab through controls and test hover, selection and disabled states. Confirm keyboard focus is visible, and delete/error controls stay red while success labels/icons stay green.
4. Open existing saved results and Plotly charts; inspect legends, labels, hover tooltips, gridlines and comparison markers/dashes. Confirm values and saved results remain unchanged.
5. Switch to light mode and reload. Confirm the saved preference, readable controls and charts, and existing light palette. Check narrow navigation and table scrolling at a mobile viewport.
