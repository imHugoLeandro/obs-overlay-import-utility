import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// Detect system theme and set data-theme attribute on documentElement.
// This allows CSS variables to switch between light and dark.
function applySystemTheme(): void {
  const root = document.documentElement;
  if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
    root.setAttribute("data-theme", "dark");
  } else {
    root.setAttribute("data-theme", "light");
  }
}

applySystemTheme();

// Listen for system theme changes.
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", applySystemTheme);

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
