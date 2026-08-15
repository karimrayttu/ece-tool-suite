// Sidecar lifecycle: resolve the Python interpreter, spawn the FastAPI backend on
// localhost, and wait for /health. Shared by the Electron main process (main.js) and the
// headless packaging smoke test (smoke.js) so both exercise the exact same launch path.

const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

// Dev: backend/.venv (editable source). Packaged: the self-contained CPython runtime under
// resources/backend/runtime — a relocatable python-build-standalone dist with ece_suite and
// every dependency pip-installed into it, so it starts on ANY Windows machine (a venv would
// not: its pyvenv.cfg points at the build machine's base interpreter).
// ECE_SUITE_RESOURCES overrides resource resolution so the packaging smoke test can point at
// release\win-unpacked\resources and exercise the REAL packaged layout on the build machine.
function resolvePython() {
  const repoRoot = path.resolve(__dirname, "..", "..");
  const res = process.env.ECE_SUITE_RESOURCES || process.resourcesPath || repoRoot;
  // venv layout differs by platform: Scripts\python.exe on Windows, bin/python elsewhere.
  const win = process.platform === "win32";
  const exe = win ? "python.exe" : "python";
  const bin = win ? "Scripts" : "bin";
  const runtime = (root) => (win
    ? { python: path.join(root, "backend", "runtime", exe), cwd: path.join(root, "backend") }
    : { python: path.join(root, "backend", "runtime", "bin", exe), cwd: path.join(root, "backend") });

  const candidates = [];
  if (process.env.ECE_SUITE_RESOURCES) candidates.push(runtime(res));
  candidates.push(
    { python: path.join(repoRoot, "backend", ".venv", bin, exe),
      cwd: path.join(repoRoot, "backend") },                       // dev checkout
    runtime(res),                                                  // packaged (portable runtime)
    runtime(repoRoot),                                             // runtime built in-repo
  );
  for (const c of candidates) if (fs.existsSync(c.python)) return c;

  // Nothing on disk. Fall back to whatever interpreter is on PATH so the failure comes from
  // Python ("No module named ece_suite") rather than from a missing file, which is a much
  // more useful thing to show the user.
  const fallback = process.env.ECE_SUITE_PYTHON || (win ? "python" : "python3");
  return { python: fallback, cwd: path.join(repoRoot, "backend") };
}

// The built renderer ships as extraResources at resources/renderer/dist (packaged) or lives at
// apps/renderer/dist (dev). Point the backend at it so it can ALSO serve the UI at "/" — the
// Electron window still loads via file://, but this gives a working browser fallback and makes the
// backend a complete single-process app.
function resolveDist() {
  const repoRoot = path.resolve(__dirname, "..", "..");
  const res = process.env.ECE_SUITE_RESOURCES || process.resourcesPath || repoRoot;
  const candidates = [
    path.join(res, "renderer", "dist"),               // packaged
    path.join(repoRoot, "apps", "renderer", "dist"),  // dev checkout
  ];
  return candidates.find((d) => fs.existsSync(path.join(d, "index.html"))) || "";
}

function spawnSidecar({ port = 8848, host = "127.0.0.1", nonce = "" } = {}) {
  const { python, cwd } = resolvePython();
  const proc = spawn(python, ["-m", "ece_suite.main", "--host", host, "--port", String(port)], {
    cwd,
    env: { ...process.env, ECE_SUITE_PORT: String(port), ECE_SUITE_NONCE: nonce,
           ECE_SUITE_DIST: resolveDist() },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,   // python.exe is a console-subsystem exe — never flash a console
  });
  // ALWAYS drain stdout/stderr: uvicorn logs synchronously, and an undrained 64KB OS pipe
  // buffer would eventually block the backend mid-session (server freeze). Keep a tail so a
  // startup failure can be shown to the user instead of a silent dead UI.
  const tail = [];
  const keep = (chunk) => {
    for (const line of String(chunk).split(/\r?\n/)) {
      if (!line.trim()) continue;
      tail.push(line);
      if (tail.length > 60) tail.shift();
    }
  };
  proc.stdout.on("data", keep);
  proc.stderr.on("data", keep);
  const baseUrl = `http://${host}:${port}`;
  return { proc, baseUrl, python, outputTail: () => tail.join("\n") };
}

async function waitForHealth(baseUrl, { timeoutMs = 20000, intervalMs = 250, nonce = "" } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastErr;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${baseUrl}/health`);
      if (r.ok) {
        const h = await r.json();
        // Identity check: only adopt the server WE launched. A stale orphan from a crashed
        // run (or an unrelated app on this port) answers /health without our nonce.
        if (!nonce || h.nonce === nonce) return h;
        lastErr = new Error("a different server answered /health (nonce mismatch)");
      }
    } catch (e) {
      lastErr = e;
    }
    await new Promise((res) => setTimeout(res, intervalMs));
  }
  throw new Error(`sidecar /health not ready in ${timeoutMs}ms: ${lastErr}`);
}

module.exports = { resolvePython, spawnSidecar, waitForHealth };
