# V1 petrol / apricot / glacier refinement

Completed shared light/dark tokens with restrained tinted selections and apricot indicators. Solid accent fills are reserved for primary actions. The top bar now has one 44px emoji button: dark shows ☀️ (Switch to light theme), light shows 🌙 (Switch to dark theme). It has a native button accessible name, action tooltip, keyboard activation and visible focus.

The inline head bootstrap resolves missing or saved System preferences from the OS once, stores the resulting Light/Dark choice, and thereafter stays fixed until toggled. Persistence, blocked storage and cross-tab behavior are tested. The favicon is petrol/apricot too. The sidebar control border was adjusted to #748F9B to clear 3:1 on its hover surface.

All five frontend test files pass, including chart fixtures and preference migration; the separate production build passes. 150 contrast pairs pass (normal text minimum 4.99:1, meaningful controls 3.07:1). No model calls were used. Existing Plotly theme updates keep stable view revisions and unchanged chart values; correlation remains diverging around zero, and PNG pixels remain untouched. Calculation/publication/persistence contracts and pane controls were not changed. Browser rendering remains unverified.

Browser checklist:

1. Toggle ☀️/🌙 by click and keyboard, check the action tooltip/focus, then reload. The chosen mode should persist.
2. For migration testing, set localStorage key analyst-theme to system, reload, and confirm it becomes the current OS mode. Subsequent OS changes must not change the saved mode; the button toggles only Light/Dark. With the key removed, initial mode should come from the OS.
3. Open saved tables and charts. Keep sort/page and chart zoom/legend state, switch themes, and confirm values and view remain. Inspect selection indicators, hover cards, correlation scale, PNG surfaces and existing chat/error/code content.
4. At narrow widths, check the emoji hit area, single-pane navigation, pane collapse and resizing. No live model requests are needed.
