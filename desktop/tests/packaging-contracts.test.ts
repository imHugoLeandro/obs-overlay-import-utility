import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import packageJson from "../package.json";

const { packageBackend } = require("../scripts/package-backend.cjs") as {
  packageBackend(options: {
    python?: string;
    run?: (...args: unknown[]) => { status: number | null; error?: Error };
    desktop?: string;
  }): number;
};

const desktop = path.resolve(__dirname, "..");
const root = path.resolve(desktop, "..");
const electronBuildScript = fs.readFileSync(
  path.join(root, "scripts", "build_portable_electron.ps1"),
  "utf8"
);

describe("Windows packaging contracts", () => {
  it("packages the backend with the explicit dedicated Python executable", () => {
    const calls: unknown[][] = [];
    const status = packageBackend({
      python: "C:\\repo\\.venv-build-electron\\Scripts\\python.exe",
      desktop,
      run: (...args) => {
        calls.push(args);
        return { status: 0 };
      },
    });

    expect(status).toBe(0);
    expect(calls).toHaveLength(1);
    const [executable, args] = calls[0];
    expect(executable).toBe("C:\\repo\\.venv-build-electron\\Scripts\\python.exe");
    expect(args).toContain(path.join(root, "tools", "desktop_backend.py"));
    expect(args).not.toContain(path.join(root, "tools", "launcher.py"));
    expect(args).not.toContain(path.join(root, "src", "obs_overlay_import_utility", "ui.py"));
  });

  it("rejects a missing configured Python executable instead of using a system default", () => {
    expect(() => packageBackend({ python: "", desktop })).toThrow(
      "OBS_OVERLAY_BUILD_PYTHON"
    );
  });

  it("delegates backend packaging from package.json and preserves the packaged backend resource", () => {
    expect(packageJson.scripts["package:backend"]).toBe("node scripts/package-backend.cjs");
    expect(packageJson.build.extraResources).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ to: "obs-overlay-backend.exe" }),
      ])
    );
  });

  it("only removes dependencies when CleanDependencies is explicitly requested", () => {
    expect(electronBuildScript).toMatch(
      /if \(\$RemoveExisting -and \(Test-Path -LiteralPath \$NodeModules\)\)/
    );
    expect(electronBuildScript).toContain("[switch]$CleanDependencies");
    expect(electronBuildScript).toContain("Install-ElectronDependencies $Desktop $CleanDependencies.IsPresent");
    expect(electronBuildScript).toContain("npm ci");
    expect(electronBuildScript).not.toMatch(/Stop-Process|taskkill|Get-Process/);
  });

  it("reports a dependency-cleanup failure without terminating unrelated processes", () => {
    expect(electronBuildScript).toContain("Could not remove $NodeModules.");
    expect(electronBuildScript).toContain("Close only the application or terminal using this repository");
    expect(electronBuildScript).not.toMatch(/Stop-Process|taskkill|Get-Process/);
  });
});
