// Resolve the backend interpreter and run it. Used by the npm scripts so the same
// commands work on Windows (backend\.venv\Scripts\python.exe) and POSIX
// (backend/.venv/bin/python) without duplicating every script.
//
//   node scripts/python.js -m pytest -q
//   node scripts/python.js -m ece_suite.main

const { spawn } = require("node:child_process");
const { existsSync } = require("node:fs");
const path = require("node:path");

const repo = path.resolve(__dirname, "..");
const backend = path.join(repo, "backend");

const candidates = [
  path.join(backend, ".venv", "Scripts", "python.exe"),
  path.join(backend, ".venv", "bin", "python"),
  path.join(backend, "runtime", "python.exe"), // bundled runtime in a packaged build
];

const python = candidates.find(existsSync);

if (!python) {
  console.error(
    "No backend interpreter found. Run scripts/setup.ps1 (Windows) or scripts/setup.sh first.",
  );
  process.exit(1);
}

module.exports = { python, backend };

if (require.main === module) {
  const child = spawn(python, process.argv.slice(2), { cwd: backend, stdio: "inherit" });
  child.on("exit", (code, signal) => process.exit(signal ? 1 : code ?? 0));
}
