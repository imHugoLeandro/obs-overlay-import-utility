"use strict";

const { spawnSync } = require("node:child_process");
const path = require("node:path");

function buildPyInstallerArgs(root) {
  return [
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "obs-overlay-backend",
    path.join(root, "tools", "desktop_backend.py"),
    "--paths", path.join(root, "src"),
    "--collect-data", "obs_overlay_import_utility",
    "--distpath", path.join(root, "build", "backend"),
    "--workpath", path.join(root, "build", "backend-work"),
    "--specpath", path.join(root, "build", "backend"),
  ];
}

function packageBackend({
  python = process.env.OBS_OVERLAY_BUILD_PYTHON,
  run = spawnSync,
  desktop = path.resolve(__dirname, ".."),
} = {}) {
  if (!python) {
    throw new Error(
      "OBS_OVERLAY_BUILD_PYTHON must name the dedicated Electron build-environment Python executable."
    );
  }

  const root = path.resolve(desktop, "..");
  const result = run(python, buildPyInstallerArgs(root), {
    cwd: desktop,
    stdio: "inherit",
  });

  if (result.error) {
    throw new Error(`Could not start the configured build Python: ${result.error.message}`);
  }
  return result.status ?? 1;
}

if (require.main === module) {
  try {
    process.exitCode = packageBackend();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

module.exports = { buildPyInstallerArgs, packageBackend };
