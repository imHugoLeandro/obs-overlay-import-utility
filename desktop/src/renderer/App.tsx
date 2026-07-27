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
import "./App.css";

/**
 * Render the content for the active page.
 * Import is the functional Fix Scene Collection Paths workflow.
 * Export and Auto Resizer are placeholder pages.
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
        <div className="page-note">
          <p>
            This page is a foundation placeholder. Only the temporary
            theme selector is available. Python settings integration
            belongs to a later Stage-2 milestone.
          </p>
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
          Foundation stage — the Fix Scene Collection Paths import workflow is
          implemented. Export, Resizer, and Settings pages are not yet
          implemented.
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
