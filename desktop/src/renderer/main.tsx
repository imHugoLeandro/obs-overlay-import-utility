import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// ThemeProvider is the sole owner of document.documentElement.dataset.theme.
// Do not set it here — that would create a competing listener that could
// overwrite an explicit user choice of Light or Dark.

const container = document.getElementById("root");
if (!container) {
  throw new Error("Failed to find the root element");
}
const root = createRoot(container);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
