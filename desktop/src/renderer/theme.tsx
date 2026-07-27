/**
 * Theme system for the React desktop shell.
 *
 * Mirrors the Social Space visual language from the Python Tk UI
 * (src/obs_overlay_import_utility/appearance.py).  Theme state lives
 * entirely in React for now; Python settings integration belongs to
 * a later Stage-2 milestone.
 *
 * ThemeProvider is the sole owner of document.documentElement.dataset.theme.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/** Theme mode: light, dark, or system preference. */
export type ThemeMode = "light" | "dark" | "system";

/** Semantic palette matching the Python Palette dataclass. */
export interface Palette {
  mode: "light" | "dark";
  background: string;
  surface: string;
  surfaceAlt: string;
  foreground: string;
  muted: string;
  border: string;
  field: string;
  disabled: string;
  accent: string;
  accentHover: string;
  accentPressed: string;
  sidebar: string;
  sidebarHover: string;
  sidebarSelected: string;
  sidebarForeground: string;
  sidebarMuted: string;
  consoleBackground: string;
  consoleForeground: string;
  selection: string;
}

/** Light palette — mirrors LIGHT_PALETTE from appearance.py. */
export const LIGHT_PALETTE: Palette = {
  mode: "light",
  background: "#F3F5F7",
  surface: "#FFFFFF",
  surfaceAlt: "#E9EDF1",
  foreground: "#171A1F",
  muted: "#626A75",
  border: "#D4DAE1",
  field: "#FFFFFF",
  disabled: "#E5E9EE",
  accent: "#E1262F",
  accentHover: "#C91E27",
  accentPressed: "#A91820",
  sidebar: "#15181D",
  sidebarHover: "#252A32",
  sidebarSelected: "#343A45",
  sidebarForeground: "#F7F8FA",
  sidebarMuted: "#A8B0BC",
  consoleBackground: "#111419",
  consoleForeground: "#E9EDF2",
  selection: "#E1262F",
};

/** Dark palette — mirrors DARK_PALETTE from appearance.py. */
export const DARK_PALETTE: Palette = {
  mode: "dark",
  background: "#101318",
  surface: "#191D23",
  surfaceAlt: "#222730",
  foreground: "#F4F6F8",
  muted: "#AAB2BE",
  border: "#303640",
  field: "#15191F",
  disabled: "#2A3038",
  accent: "#E1262F",
  accentHover: "#D9363E",
  accentPressed: "#B71F28",
  sidebar: "#0A0C10",
  sidebarHover: "#1C2128",
  sidebarSelected: "#2B313B",
  sidebarForeground: "#F7F8FA",
  sidebarMuted: "#A8B0BC",
  consoleBackground: "#090B0E",
  consoleForeground: "#E9EDF2",
  selection: "#F0444C",
};

/**
 * Detect the system color scheme.
 * Returns "dark" if the OS prefers dark, "light" otherwise.
 */
export function systemThemeMode(): "light" | "dark" {
  if (typeof window !== "undefined" && window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return "light";
}

/**
 * Resolve a theme mode to a concrete palette.
 * When mode is "system", uses the current OS preference via matchMedia.
 * This is a pure utility — the ThemeProvider derives palette from
 * systemMode state for reactive updates.
 */
export function paletteFor(mode: ThemeMode): Palette {
  if (mode === "system") {
    return systemThemeMode() === "dark" ? DARK_PALETTE : LIGHT_PALETTE;
  }
  return mode === "dark" ? DARK_PALETTE : LIGHT_PALETTE;
}

/** Theme labels matching the Python THEME_LABELS. */
export const THEME_LABELS: Record<ThemeMode, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

/** Theme options for the settings selector. */
export const THEME_OPTIONS: ThemeMode[] = ["system", "light", "dark"];

interface ThemeContextValue {
  theme: ThemeMode;
  palette: Palette;
  setTheme: (mode: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

/**
 * Hook to access the current theme context.
 * Must be used within a ThemeProvider.
 */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}

interface ThemeProviderProps {
  children: ReactNode;
  initialTheme?: ThemeMode;
}

/**
 * Theme provider — the sole owner of document.documentElement.dataset.theme.
 *
 * State:
 * - theme: the user-selected mode (light, dark, or system)
 * - systemMode: the current OS color-scheme preference (light or dark)
 *
 * When theme is "system", the palette and data-theme are derived from
 * systemMode, which is kept in sync with matchMedia changes.
 * When theme is explicitly "light" or "dark", OS preference changes
 * do NOT alter the palette or data-theme.
 */
export function ThemeProvider({
  children,
  initialTheme = "system",
}: ThemeProviderProps): React.ReactElement {
  const [theme, setThemeState] = useState<ThemeMode>(initialTheme);
  const [systemMode, setSystemMode] = useState<"light" | "dark">(
    systemThemeMode()
  );

  // Derive the resolved mode: system preference or explicit choice.
  const resolvedMode = theme === "system" ? systemMode : theme;

  // Derive the palette from the resolved mode.
  const palette = useMemo(
    () => (resolvedMode === "dark" ? DARK_PALETTE : LIGHT_PALETTE),
    [resolvedMode]
  );

  const setTheme = (mode: ThemeMode): void => {
    setThemeState(mode);
  };

  // Subscribe to OS color-scheme changes when theme is "system".
  // When theme is explicitly light/dark, no listener is attached,
  // so OS changes cannot override the user's choice.
  useEffect(() => {
    if (theme !== "system") return;

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const handler = (event: MediaQueryListEvent): void => {
      setSystemMode(event.matches ? "dark" : "light");
    };

    mediaQuery.addEventListener("change", handler);
    return () => {
      mediaQuery.removeEventListener("change", handler);
    };
  }, [theme]);

  // Apply the resolved mode to documentElement as data-theme.
  // ThemeProvider is the sole owner of this attribute.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolvedMode);
  }, [resolvedMode]);

  const value = useMemo(
    () => ({ theme, palette, setTheme }),
    [theme, palette]
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}
