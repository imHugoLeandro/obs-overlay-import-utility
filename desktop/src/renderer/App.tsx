/**
 * App component — the Social Space React application shell.
 *
 * Layout:
 * - Persistent navigation sidebar (Import, Export, Auto Resizer, Settings)
 * - Main content area with the Import page and placeholder pages
 * - Backend status area (health + app version)
 *
 * Theme state lives in React only.  No Python settings integration yet.
 */

import React from "react";
import {
  ThemeProvider,
} from "./theme";
import {
  Navigation,
  type PageId,
  NAV_ITEMS,
} from "./Navigation";
import { PlaceholderPage } from "./PlaceholderPages";
import { ThemeSelector } from "./ThemeSelector";
import { BackendStatus } from "./BackendStatus";
import { ImportPage } from "./ImportPage";
import { ExportPage } from "./ExportPage";
import "./App.css";

/**
 * Render the content for the active page.
 * Import and Export are functional pages.
 * Auto Resizer is a placeholder (Stage 3).
 * Settings exposes only the theme selector.
 */
function PageContent({
  activePage,
}: {
  activePage: PageId;
}): React.ReactElement {
  const item = NAV_ITEMS.find((n) => n.id === activePage);

  if (activePage === "import") {
    return <ImportPage />;
  }

  if (activePage === "export") {
    return <ExportPage />;
  }

  if (activePage === "settings") {
    return (
      <section
        className="page-content"
        aria-labelledby="settings-title"
      >
        <h1 id="settings-title" className="page-title">
          Settings
        </h1>
        <p className="page-description">
          Application settings for the OBS Overlay Import Utility.
        </p>
        <div className="settings-section">
          <ThemeSelector />
        </div>
      </section>
    );
  }

  if (!item) {
    return (
      <PlaceholderPage
        pageId={activePage}
        title="Not Found"
        description="This page does not exist."
      />
    );
  }

  return (
    <PlaceholderPage
      pageId={activePage}
      title={item.label}
      description={item.description}
    />
  );
}

/**
 * Main application component.
 * Wraps everything in ThemeProvider and manages the active page state.
 */
function AppContent(): React.ReactElement {
  const [activePage, setActivePage] = React.useState<PageId>("import");

  return (
    <div className="app-shell">
      <Navigation
        activePage={activePage}
        onNavigate={setActivePage}
      />
      <main className="app-main">
        <PageContent activePage={activePage} />
        <BackendStatus />
      </main>
      <footer className="app-footer">
        <p>
          Stage 2 — Import (Fix Scene Collection Paths, Streamlabs, Automatic,
          Device Setup, OBS Activation) and Export workflows are implemented.
          Auto Resizer is coming in Stage 3.
        </p>
      </footer>
    </div>
  );
}

/**
 * Root App component.
 * Provides the ThemeProvider wrapper.
 */
function App(): React.ReactElement {
  return (
    <ThemeProvider initialTheme="system">
      <AppContent />
    </ThemeProvider>
  );
}

export default App;
