/**
 * Placeholder pages for the OBS Overlay Import Utility desktop shell.
 *
 * These are presentational only — no real file selection, imports,
 * exports, or OBS actions.  Business workflows come in later stages.
 */

import React from "react";
import type { PageId } from "./Navigation";

/** Props for all placeholder pages. */
interface PlaceholderPageProps {
  pageId: PageId;
  title: string;
  description: string;
}

/**
 * Generic placeholder page.
 * Shows a title and description explaining the workflow is coming next.
 */
export function PlaceholderPage({
  title,
  description,
}: PlaceholderPageProps): React.ReactElement {
  return (
    <section className="placeholder-page" aria-labelledby="placeholder-title">
      <h1 id="placeholder-title" className="placeholder-title">
        {title}
      </h1>
      <p className="placeholder-description">{description}</p>
      <div className="placeholder-note">
        <p>
          This page is a foundation placeholder. The full workflow is not
          yet implemented in the Electron shell.
        </p>
      </div>
    </section>
  );
}

/**
 * Settings page placeholder.
 * Exposes only the temporary theme selector.
 */
export function SettingsPage(): React.ReactElement {
  return (
    <section
      className="placeholder-page"
      aria-labelledby="settings-title"
    >
      <h1 id="settings-title" className="placeholder-title">
        Settings
      </h1>
      <p className="placeholder-description">
        Application settings for the OBS Overlay Import Utility.
      </p>
      <div className="placeholder-note">
        <p>
          This page is a foundation placeholder. Only the temporary theme
          selector is available. Python settings integration belongs to a
          later Stage-2 milestone.
        </p>
      </div>
    </section>
  );
}
