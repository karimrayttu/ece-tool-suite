// Guard for `npm run dist`. The bundled CPython under backend/runtime is a build input, not
// something the repo carries, and electron-builder will happily produce an installer without
// it that fails on first launch. Fail here instead, with the instructions.

const { existsSync } = require("node:fs");
const path = require("node:path");

const repo = path.resolve(__dirname, "..");
const runtime = path.join(repo, "backend", "runtime", "python.exe");

if (process.platform !== "win32") {
  console.error(
    "Packaging is Windows-only: electron-builder has no mac or linux target configured and\n" +
      "the bundled interpreter is a Windows CPython. Run from source instead (npm run app).",
  );
  process.exit(1);
}

if (!existsSync(runtime)) {
  console.error(
    `Missing ${path.relative(repo, runtime)}.\n\n` +
      "The distributable carries a self-contained CPython 3.12 rather than the dev venv,\n" +
      "because a venv is not relocatable. Build it once with the steps in\n" +
      "docs/packaging.md, then run `npm run dist` again.",
  );
  process.exit(1);
}
