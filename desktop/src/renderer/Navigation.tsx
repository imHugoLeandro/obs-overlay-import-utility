/**
 * Navigation sidebar for the OBS Overlay Import Utility desktop shell.
 *
 * Provides persistent top-level navigation for Import, Export, Auto Resizer,
 * and Settings.  Keyboard-accessible, responsive, and follows the Social
 * Space visual language from the Python Tk UI.
 */

import React from "react";
import { useTheme } from "./theme";

/** Navigation page identifiers. */
export type PageId = "import" | "export" | "resizer" | "settings";

/** Navigation item definition. */
export interface NavItem {
  id: PageId;
  label: string;
  /** Short description shown on the placeholder page. */
  description: string;
}

/** Navigation items matching the Python SECTIONS tuple. */
export const NAV_ITEMS: NavItem[] = [
  {
    id: "import",
    label: "Import",
    description: "Import workflows are coming next.",
  },
  {
    id: "export",
    label: "Export",
    description: "Export workflows are coming next.",
  },
  {
    id: "resizer",
    label: "Auto Resizer",
    description: "Auto Resizer workflows are coming next.",
  },
  {
    id: "settings",
    label: "Settings",
    description: "Application settings.",
  },
];

interface NavigationProps {
  activePage: PageId;
  onNavigate: (page: PageId) => void;
}

/**
 * Navigation sidebar component.
 *
 * - Persistent vertical navigation on the left.
 * - Keyboard-accessible (arrow keys, Enter, Home/End).
 * - Clear active state with accent color.
 * - Responsive: collapses to icon-only on narrow windows.
 * - Uses native <nav> with buttons — no role="menubar"/"menuitem".
 * - Active page uses aria-current="page" only (no aria-selected).
 */
export function Navigation({
  activePage,
  onNavigate,
}: NavigationProps): React.ReactElement {
  const { palette } = useTheme();
  const navRef = React.useRef<HTMLElement>(null);
  const [focusedIndex, setFocusedIndex] = React.useState<number>(-1);

  // Handle keyboard navigation within the nav.
  const handleKeyDown = (
    event: React.KeyboardEvent<HTMLElement>,
    index: number
  ): void => {
    const itemCount = NAV_ITEMS.length;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setFocusedIndex((index + 1) % itemCount);
        break;
      case "ArrowUp":
        event.preventDefault();
        setFocusedIndex((index - 1 + itemCount) % itemCount);
        break;
      case "Home":
        event.preventDefault();
        setFocusedIndex(0);
        break;
      case "End":
        event.preventDefault();
        setFocusedIndex(itemCount - 1);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        onNavigate(NAV_ITEMS[index].id);
        setFocusedIndex(-1);
        break;
      case "Escape":
        event.preventDefault();
        setFocusedIndex(-1);
        break;
    }
  };

  // Move focus to the focused item after render.
  React.useEffect(() => {
    if (focusedIndex >= 0 && navRef.current) {
      const buttons = navRef.current.querySelectorAll<HTMLButtonElement>(
        "button[data-nav-index]"
      );
      buttons[focusedIndex]?.focus();
    }
  }, [focusedIndex]);

  return (
    <nav
      className="navigation"
      aria-label="Main navigation"
      ref={navRef}
      style={
        {
          "--nav-bg": palette.sidebar,
          "--nav-bg-hover": palette.sidebarHover,
          "--nav-bg-selected": palette.sidebarSelected,
          "--nav-fg": palette.sidebarForeground,
          "--nav-fg-muted": palette.sidebarMuted,
          "--nav-accent": palette.accent,
        } as React.CSSProperties
      }
    >
      <div className="nav-header">
        <span className="nav-caption">OVERLAY TOOLS</span>
      </div>
      <ul className="nav-list">
        {NAV_ITEMS.map((item, index) => {
          const isActive = activePage === item.id;
          const isFocused = focusedIndex === index;
          return (
            <li key={item.id}>
              <button
                type="button"
                data-nav-index={index}
                aria-current={isActive ? "page" : undefined}
                className={`nav-button ${isActive ? "active" : ""} ${
                  isFocused ? "focused" : ""
                }`}
                onClick={() => {
                  onNavigate(item.id);
                  setFocusedIndex(-1);
                }}
                onKeyDown={(e) => handleKeyDown(e, index)}
                tabIndex={isActive ? 0 : -1}
              >
                <span className="nav-label">{item.label}</span>
                {isActive && (
                  <span
                    className="nav-indicator"
                    aria-hidden="true"
                  />
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
