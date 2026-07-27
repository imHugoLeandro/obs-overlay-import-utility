/**
 * Tests for the Navigation component.
 *
 * Tests:
 * - Renders all four navigation items
 * - Active page has correct aria-current and active class
 * - Clicking a nav item calls onNavigate with the correct page
 * - Keyboard navigation: ArrowDown, ArrowUp, Enter, Home, End, Escape
 * - Focus states are applied correctly
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Navigation } from "../src/renderer/Navigation";
import { ThemeProvider } from "../src/renderer/theme";

function renderNav(
  activePage: "import" | "export" | "resizer" | "settings" = "import",
  onNavigate = vi.fn()
) {
  return render(
    <ThemeProvider initialTheme="light">
      <Navigation activePage={activePage} onNavigate={onNavigate} />
    </ThemeProvider>
  );
}

describe("Navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all four navigation items", () => {
    renderNav();
    expect(screen.getByText("Import")).toBeInTheDocument();
    expect(screen.getByText("Export")).toBeInTheDocument();
    expect(screen.getByText("Auto Resizer")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("marks the active page with aria-current", () => {
    renderNav("export");
    const exportButton = screen.getByRole("menuitem", { name: "Export" });
    expect(exportButton).toHaveAttribute("aria-current", "page");
    expect(exportButton).toHaveClass("active");
  });

  it("does not mark inactive pages with aria-current", () => {
    renderNav("import");
    const exportButton = screen.getByRole("menuitem", { name: "Export" });
    expect(exportButton).not.toHaveAttribute("aria-current");
    expect(exportButton).not.toHaveClass("active");
  });

  it("calls onNavigate with the correct page when a nav item is clicked", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderNav("import", onNavigate);

    await user.click(screen.getByRole("menuitem", { name: "Export" }));
    expect(onNavigate).toHaveBeenCalledWith("export");
  });

  it("calls onNavigate for each nav item", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderNav("import", onNavigate);

    await user.click(screen.getByRole("menuitem", { name: "Import" }));
    expect(onNavigate).toHaveBeenCalledWith("import");

    await user.click(screen.getByRole("menuitem", { name: "Auto Resizer" }));
    expect(onNavigate).toHaveBeenCalledWith("resizer");

    await user.click(screen.getByRole("menuitem", { name: "Settings" }));
    expect(onNavigate).toHaveBeenCalledWith("settings");
  });

  it("supports keyboard navigation with ArrowDown", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const firstButton = screen.getByRole("menuitem", { name: "Import" });
    firstButton.focus();
    await user.keyboard("{ArrowDown}");

    const secondButton = screen.getByRole("menuitem", { name: "Export" });
    expect(secondButton).toHaveFocus();
  });

  it("supports keyboard navigation with ArrowUp", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const secondButton = screen.getByRole("menuitem", { name: "Export" });
    secondButton.focus();
    await user.keyboard("{ArrowUp}");

    const firstButton = screen.getByRole("menuitem", { name: "Import" });
    expect(firstButton).toHaveFocus();
  });

  it("supports Enter to navigate via keyboard", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderNav("import", onNavigate);

    const exportButton = screen.getByRole("menuitem", { name: "Export" });
    exportButton.focus();
    await user.keyboard("{Enter}");

    expect(onNavigate).toHaveBeenCalledWith("export");
  });

  it("supports Space to navigate via keyboard", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderNav("import", onNavigate);

    const settingsButton = screen.getByRole("menuitem", { name: "Settings" });
    settingsButton.focus();
    await user.keyboard(" ");

    expect(onNavigate).toHaveBeenCalledWith("settings");
  });

  it("supports Home and End keys", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const lastButton = screen.getByRole("menuitem", { name: "Settings" });
    lastButton.focus();
    await user.keyboard("{Home}");

    const firstButton = screen.getByRole("menuitem", { name: "Import" });
    expect(firstButton).toHaveFocus();

    await user.keyboard("{End}");
    expect(lastButton).toHaveFocus();
  });

  it("supports Escape to clear focus state", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const firstButton = screen.getByRole("menuitem", { name: "Import" });
    firstButton.focus();
    await user.keyboard("{ArrowDown}");

    // After ArrowDown, the second button should have the "focused" class.
    const secondButton = screen.getByRole("menuitem", { name: "Export" });
    expect(secondButton).toHaveClass("focused");

    // Escape should clear the focused state.
    await user.keyboard("{Escape}");

    // The focused class should be removed from all buttons.
    const navButtons = screen.getAllByRole("menuitem");
    navButtons.forEach((btn) => {
      expect(btn).not.toHaveClass("focused");
    });
  });

  it("has accessible label for the navigation region", () => {
    renderNav();
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
  });

  it("wraps around with ArrowDown on the last item", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const lastButton = screen.getByRole("menuitem", { name: "Settings" });
    lastButton.focus();
    await user.keyboard("{ArrowDown}");

    const firstButton = screen.getByRole("menuitem", { name: "Import" });
    expect(firstButton).toHaveFocus();
  });

  it("wraps around with ArrowUp on the first item", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const firstButton = screen.getByRole("menuitem", { name: "Import" });
    firstButton.focus();
    await user.keyboard("{ArrowUp}");

    const lastButton = screen.getByRole("menuitem", { name: "Settings" });
    expect(lastButton).toHaveFocus();
  });
});
