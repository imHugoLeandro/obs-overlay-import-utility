/**
 * Theme selector component for the Settings page.
 *
 * Allows the user to choose between System, Light, and Dark themes.
 * Theme state is kept in React only (no persistence to Python settings).
 */

import React from "react";
import { useTheme, THEME_OPTIONS, THEME_LABELS, systemThemeMode } from "./theme";

/**
 * Theme selector dropdown.
 * Shows the current theme and allows switching.
 * When "System" is selected, shows the detected system preference.
 */
export function ThemeSelector(): React.ReactElement {
  const { theme, setTheme, palette } = useTheme();
  const selectRef = React.useRef<HTMLSelectElement>(null);

  // Detect system preference for display purposes.
  const [systemPref, setSystemPref] = React.useState<"light" | "dark">(
    systemThemeMode()
  );

  React.useEffect(() => {
    if (theme !== "system") return;

    const update = (): void => setSystemPref(systemThemeMode());
    update();

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, [theme]);

  const handleChange = (
    event: React.ChangeEvent<HTMLSelectElement>
  ): void => {
    const value = event.target.value as typeof theme;
    setTheme(value);
  };

  return (
    <div className="theme-selector">
      <label htmlFor="theme-select" className="theme-selector-label">
        Theme
      </label>
      <select
        id="theme-select"
        ref={selectRef}
        className="theme-select"
        value={theme}
        onChange={handleChange}
        style={
          {
            "--select-bg": palette.field,
            "--select-border": palette.border,
            "--select-fg": palette.foreground,
            "--select-bg-hover": palette.surfaceAlt,
          } as React.CSSProperties
        }
      >
        {THEME_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {THEME_LABELS[option]}
          </option>
        ))}
      </select>
      {theme === "system" && (
        <span className="theme-system-info">
          System preference: {systemPref === "dark" ? "Dark" : "Light"}
        </span>
      )}
    </div>
  );
}
