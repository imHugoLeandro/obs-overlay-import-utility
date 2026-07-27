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
    expect(screen.getByRole("button", { name: "Import" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Auto Resizer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
  });

  it("marks the active page with aria-current", () => {
    renderNav("export");
    const exportButton = screen.getByRole("button", { name: "Export" });
    expect(exportButton).toHaveAttribute("aria-current", "page");
    expect(exportButton).toHaveClass("active");
  });

  it("does not mark inactive pages with aria-current", () => {
    renderNav("import");
    const exportButton = screen.getByRole("button", { name: "Export" });
    expect(exportButton).not.toHaveAttribute("aria-current");
    expect(exportButton).not.toHaveClass("active");
  });

  it("does not use aria-selected on navigation buttons", () => {
    renderNav("import");
    const importButton = screen.getByRole("button", { name: "Import" });
    expect(importButton).not.toHaveAttribute("aria-selected");
  });

  it("calls onNavigate with the correct page when a nav item is clicked", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderNav("import", onNavigate);

    await user.click(screen.getByRole("button", { name: "Export" }));
    expect(onNavigate).toHaveBeenCalledWith("export");
  });

  it("calls onNavigate for each nav item", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderNav("import", onNavigate);

    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(onNavigate).toHaveBeenCalledWith("import");

    await user.click(screen.getByRole("button", { name: "Auto Resizer" }));
    expect(onNavigate).toHaveBeenCalledWith("resizer");

    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(onNavigate).toHaveBeenCalledWith("settings");
  });

  it("supports keyboard navigation with ArrowDown", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const firstButton = screen.getByRole("button", { name: "Import" });
    firstButton.focus();
    await user.keyboard("{ArrowDown}");

    const secondButton = screen.getByRole("button", { name: "Export" });
    expect(secondButton).toHaveFocus();
  });

  it("supports keyboard navigation with ArrowUp", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const secondButton = screen.getByRole("button", { name: "Export" });
    secondButton.focus();
    await user.keyboard("{ArrowUp}");

    const firstButton = screen.getByRole("button", { name: "Import" });
    expect(firstButton).toHaveFocus();
  });

  it("supports Enter to navigate via keyboard", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderNav("import", onNavigate);

    const exportButton = screen.getByRole("button", { name: "Export" });
    exportButton.focus();
    await user.keyboard("{Enter}");

    expect(onNavigate).toHaveBeenCalledWith("export");
  });

  it("supports Space to navigate via keyboard", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderNav("import", onNavigate);

    const settingsButton = screen.getByRole("button", { name: "Settings" });
    settingsButton.focus();
    await user.keyboard(" ");

    expect(onNavigate).toHaveBeenCalledWith("settings");
  });

  it("supports Home and End keys", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const lastButton = screen.getByRole("button", { name: "Settings" });
    lastButton.focus();
    await user.keyboard("{Home}");

    const firstButton = screen.getByRole("button", { name: "Import" });
    expect(firstButton).toHaveFocus();

    await user.keyboard("{End}");
    expect(lastButton).toHaveFocus();
  });

  it("supports Escape to clear focus state", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const firstButton = screen.getByRole("button", { name: "Import" });
    firstButton.focus();
    await user.keyboard("{ArrowDown}");

    // After ArrowDown, the second button should have the "focused" class.
    const secondButton = screen.getByRole("button", { name: "Export" });
    expect(secondButton).toHaveClass("focused");

    // Escape should clear the focused state.
    await user.keyboard("{Escape}");

    // The focused class should be removed from all buttons.
    const navButtons = screen.getAllByRole("button");
    navButtons.forEach((btn) => {
      expect(btn).not.toHaveClass("focused");
    });
  });

  it("has accessible label for the navigation region", () => {
    renderNav();
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
  });

  it("does not use role=menubar or role=menuitem", () => {
    renderNav();
    expect(screen.queryByRole("menubar")).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });

  it("wraps around with ArrowDown on the last item", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const lastButton = screen.getByRole("button", { name: "Settings" });
    lastButton.focus();
    await user.keyboard("{ArrowDown}");

    const firstButton = screen.getByRole("button", { name: "Import" });
    expect(firstButton).toHaveFocus();
  });

  it("wraps around with ArrowUp on the first item", async () => {
    const user = userEvent.setup();
    renderNav("import");

    const firstButton = screen.getByRole("button", { name: "Import" });
    firstButton.focus();
    await user.keyboard("{ArrowUp}");

    const lastButton = screen.getByRole("button", { name: "Settings" });
    expect(lastButton).toHaveFocus();
  });
});
