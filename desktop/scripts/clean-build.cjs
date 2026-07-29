"use strict";

const fs = require("node:fs");
const path = require("node:path");

const desktop = path.resolve(__dirname, "..");
for (const directory of ["dist", "dist-electron"]) {
  fs.rmSync(path.join(desktop, directory), { recursive: true, force: true });
}
