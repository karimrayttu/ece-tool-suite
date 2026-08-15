// Run the FastAPI sidecar and the Vite dev server together, and take both down on Ctrl-C.
// The Electron shell (`npm run app`) spawns its own sidecar, so use that instead if you
// want the native window rather than a browser tab.

const { spawn } = require("node:child_process");
const path = require("node:path");

const { python, backend } = require("./python.js");

const repo = path.resolve(__dirname, "..");

// npm is a .cmd on Windows, and since Node 20 spawning a batch file without a shell fails
// with EINVAL. The arguments here are all literals, so there is nothing for the shell to
// mangle.
const win = process.platform === "win32";

const children = [
  spawn(python, ["-m", "ece_suite.main"], { cwd: backend, stdio: "inherit" }),
  spawn(win ? "npm.cmd" : "npm", ["--workspace", "apps/renderer", "run", "dev"], {
    cwd: repo,
    stdio: "inherit",
    shell: win,
  }),
];

let shuttingDown = false;

function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (child.exitCode === null) child.kill();
  }
  process.exit(code);
}

// If either process dies the other is useless, so take the whole thing down.
for (const child of children) {
  child.on("exit", (code) => shutdown(code ?? 0));
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
