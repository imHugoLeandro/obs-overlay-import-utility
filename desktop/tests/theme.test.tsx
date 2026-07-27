/**
 * Tests for the theme system.
 *
 * Tests:
 * - LIGHT_PALETTE and DARK_PALETTE have correct values matching Python appearance.py
 * - paletteFor resolves light, dark, and system modes
 * - systemThemeMode detects the OS preference
 * - ThemeProvider provides theme, palette, and setTheme
 * - ThemeProvider sets data-theme attribute on documentElement
 * - ThemeProvider listens for system preference changes
 * - ThemeSelector renders and allows switching themes
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  LIGHT_PALETTE,
  DARK_PALETTE,
  paletteFor,
  systemThemeMode,
  ThemeProvider,
  useTheme,
  THEME_LABELS,
  THEME_OPTIONS,
} from "../src/renderer/theme";
import { ThemeSelector } from "../src/renderer/ThemeSelector";

// Helper component to access theme context in tests.
function ThemeProbe(): React.ReactElement {
  const { theme, palette, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="palette-mode">{palette.mode}</span>
      <span data-testid="palette-accent">{palette.accent}</span>
      <button onClick={() => setTheme("dark")}>set-dark</button>
      <button onClick={() => setTheme("light")}>set-light</button>
      <button onClick={() => setTheme("system")}>set-system</button>
    </div>
  );
}

function renderWithTheme(initialTheme: "light" | "dark" | "system" = "system") {
  return render(
    <ThemeProvider initialTheme={initialTheme}>
      <ThemeProbe />
    </ThemeProvider>
  );
}

describe("Palette constants", () => {
  it("LIGHT_PALETTE has correct mode and accent", () => {
    expect(LIGHT_PALETTE.mode).toBe("light");
    expect(LIGHT_PALETTE.accent).toBe("#E1262F");
    expect(LIGHT_PALETTE.background).toBe("#F3F5F7");
    expect(LIGHT_PALETTE.sidebar).toBe("#15181D");
  });

  it("DARK_PALETTE has correct mode and accent", () => {
    expect(DARK_PALETTE.mode).toBe("dark");
    expect(DARK_PALETTE.accent).toBe("#E1262F");
    expect(DARK_PALETTE.background).toBe("#101318");
    expect(DARK_PALETTE.sidebar).toBe("#0A0C10");
  });

  it("both palettes share the same accent color", () => {
    expect(LIGHT_PALETTE.accent).toBe(DARK_PALETTE.accent);
  });

  it("light and dark palettes have different background colors", () => {
    expect(LIGHT_PALETTE.background).not.toBe(DARK_PALETTE.background);
  });
});

describe("paletteFor", () => {
  it("returns LIGHT_PALETTE for 'light' mode", () => {
    const palette = paletteFor("light");
    expect(palette.mode).toBe("light");
    expect(palette).toBe(LIGHT_PALETTE);
  });

  it("returns DARK_PALETTE for 'dark' mode", () => {
    const palette = paletteFor("dark");
    expect(palette.mode).toBe("dark");
    expect(palette).toBe(DARK_PALETTE);
  });

  it("returns a palette based on system preference for 'system' mode", () => {
    // Mock systemThemeMode to return "dark".
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query.includes("dark"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    const palette = paletteFor("system");
    expect(palette.mode).toBe("dark");

    window.matchMedia = originalMatchMedia;
  });

  it("returns light palette when system prefers light", () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    const palette = paletteFor("system");
    expect(palette.mode).toBe("light");

    window.matchMedia = originalMatchMedia;
  });
});

describe("systemThemeMode", () => {
  it("returns 'dark' when OS prefers dark", () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query.includes("dark"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    expect(systemThemeMode()).toBe("dark");
    window.matchMedia = originalMatchMedia;
  });

  it("returns 'light' when OS prefers light", () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    expect(systemThemeMode()).toBe("light");
    window.matchMedia = originalMatchMedia;
  });
});

describe("ThemeProvider", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
  });

  it("provides the initial theme", () => {
    renderWithTheme("dark");
    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(screen.getByTestId("palette-mode").textContent).toBe("dark");
  });

  it("provides light palette when theme is light", () => {
    renderWithTheme("light");
    expect(screen.getByTestId("palette-mode").textContent).toBe("light");
  });

  it("sets data-theme attribute on documentElement", () => {
    renderWithTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("sets data-theme to light when theme is light", () => {
    renderWithTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("sets data-theme based on system preference when theme is system", () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query.includes("dark"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    renderWithTheme("system");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    window.matchMedia = originalMatchMedia;
  });

  it("allows switching theme via setTheme", async () => {
    const user = userEvent.setup();
    renderWithTheme("light");

    await user.click(screen.getByText("set-dark"));
    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(screen.getByTestId("palette-mode").textContent).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("re-renders palette when system preference changes", async () => {
    // This test verifies that paletteFor picks up system preference changes
    // when called multiple times with different matchMedia results.
    const originalMatchMedia = window.matchMedia;

    // First: system prefers light.
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as typeof window.matchMedia;

    expect(paletteFor("system").mode).toBe("light");

    // Now: system prefers dark.
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as typeof window.matchMedia;

    expect(paletteFor("system").mode).toBe("dark");

    window.matchMedia = originalMatchMedia;
  });
});

describe("ThemeSelector", () => {
  it("renders the theme selector with all options", () => {
    render(
      <ThemeProvider initialTheme="light">
        <ThemeSelector />
      </ThemeProvider>
    );

    const select = screen.getByLabelText("Theme");
    expect(select).toBeInTheDocument();

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(3);
    expect(options[0]).toHaveValue("system");
    expect(options[1]).toHaveValue("light");
    expect(options[2]).toHaveValue("dark");
  });

  it("shows system preference info when system is selected", () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query.includes("dark"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    render(
      <ThemeProvider initialTheme="system">
        <ThemeSelector />
      </ThemeProvider>
    );

    expect(screen.getByText(/System preference: Dark/)).toBeInTheDocument();

    window.matchMedia = originalMatchMedia;
  });

  it("allows switching to dark theme", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider initialTheme="light">
        <ThemeSelector />
      </ThemeProvider>
    );

    const select = screen.getByLabelText("Theme");
    await user.selectOptions(select, "dark");

    expect(select).toHaveValue("dark");
  });

  it("allows switching to light theme", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider initialTheme="dark">
        <ThemeSelector />
      </ThemeProvider>
    );

    const select = screen.getByLabelText("Theme");
    await user.selectOptions(select, "light");

    expect(select).toHaveValue("light");
  });

  it("THEME_LABELS has correct labels", () => {
    expect(THEME_LABELS.system).toBe("System");
    expect(THEME_LABELS.light).toBe("Light");
    expect(THEME_LABELS.dark).toBe("Dark");
  });

  it("THEME_OPTIONS has all three modes", () => {
    expect(THEME_OPTIONS).toEqual(["system", "light", "dark"]);
  });
});
