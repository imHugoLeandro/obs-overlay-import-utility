/**
 * App component — the Social Space React application shell.
 *
 * Layout:
 * - Persistent navigation sidebar (Import, Export, Auto Resizer, Settings)
 * - Main content area with functional workflows and Settings
 * - Backend status area (health + app version)
 *
 * Theme state lives in React only.  No Python settings integration yet.
 */

import React from "react";
import {
  ThemeProvider,
} from "./theme";
import { Navigation, type PageId } from "./Navigation";
import { ThemeSelector } from "./ThemeSelector";
import { BackendStatus } from "./BackendStatus";
import { ImportPage } from "./ImportPage";
import { ExportPage } from "./ExportPage";
import { AutoResizerPage } from "./AutoResizerPage";
import "./App.css";

/**
 * Render the content for the active page.
 * Import, Export, and Auto Resizer are functional pages.
 * Settings exposes only the theme selector.
 */
function PageContent({
  activePage,
}: {
  activePage: PageId;
}): React.ReactElement {
  switch (activePage) {
    case "import":
      return <ImportPage />;
    case "export":
      return <ExportPage />;
    case "resizer":
      return <AutoResizerPage />;
    case "settings":
      return (
        <section className="page-content" aria-labelledby="settings-title">
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
          Available workflows: Import, Export, and Auto Resizer. Auto Resizer
          supports offline and live OBS resize.
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
