import { createContext, useContext, useSyncExternalStore } from 'react';

const ThemeContext = createContext(null);
export function ThemeProvider({ children }) {
  const store = window.analystTheme;
  const theme = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  return <ThemeContext.Provider value={{ ...theme, setPreference: store.setPreference }}>{children}</ThemeContext.Provider>;
}
export const useTheme = () => useContext(ThemeContext);
export function ThemeControl() {
  const { resolved, setPreference } = useTheme();
  const next = resolved === 'dark' ? 'light' : 'dark';
  const action = `Switch to ${next} theme`;
  return <button type="button" className="theme-toggle" aria-label={action} title={action}
    onClick={() => setPreference(next)}>
    {resolved === 'dark' ? <svg className="theme-toggle-glyph theme-toggle-sun" data-emoji="☀️" aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="4" fill="currentColor" />
      <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg> : <svg className="theme-toggle-glyph theme-toggle-moon" data-emoji="🌙" aria-hidden="true" viewBox="0 0 24 24">
      <path d="M20.7 14.4A9 9 0 0 1 9.6 3.3 9 9 0 1 0 20.7 14.4Z" fill="currentColor" />
    </svg>}
  </button>;
}
