// Electron main process: own the Python sidecar lifecycle and host the renderer.
// Self-healing: if the renderer build is missing or out of date (dev layout), it is rebuilt
// automatically before the window loads — the user never has to run `npm run build`.
const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const net = require("node:net");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const { spawnSidecar, waitForHealth } = require("./sidecar");

const PREFERRED_PORT = Number(process.env.ECE_SUITE_PORT || 8848);
const NONCE = crypto.randomUUID(); // per-launch identity so we never adopt a foreign server
let port = PREFERRED_PORT; // actual port after conflict resolution; ipc reports this
let sidecar = null;
let win = null;

// One app instance: a second launch focuses the first window instead of spawning a second
// backend that would fight over ports and the data dir.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
}

// Prefer 8848 (docs/MCP config assume it); if something else owns it, take an OS-assigned
// free port instead of silently talking to a stranger's server or failing to bind.
function findFreePort(preferred) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.once("error", () => {
      const any = net.createServer();
      any.once("listening", () => {
        const p = any.address().port;
        any.close(() => resolve(p));
      });
      any.listen(0, "127.0.0.1");
    });
    probe.once("listening", () => probe.close(() => resolve(preferred)));
    probe.listen(preferred, "127.0.0.1");
  });
}

const rendererDir = () => path.join(__dirname, "..", "renderer");
const devDistIndex = () => path.join(rendererDir(), "dist", "index.html");
const packagedIndex = () => path.join(process.resourcesPath || "", "renderer", "dist", "index.html");

function mtime(p) {
  try { return fs.statSync(p).mtimeMs; } catch { return 0; }
}

// Newest mtime of any file under a directory (skips node_modules/dist).
function newestUnder(dir) {
  let newest = 0;
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return 0; }
  for (const e of entries) {
    if (e.name === "node_modules" || e.name === "dist" || e.name.startsWith(".")) continue;
    const full = path.join(dir, e.name);
    newest = Math.max(newest, e.isDirectory() ? newestUnder(full) : mtime(full));
  }
  return newest;
}

// App icon: repo layout in dev, extraResources when packaged.
function appIcon() {
  const candidates = [
    path.join(__dirname, "..", "..", "assets", "ece-tool-suite.ico"),
    path.join(process.resourcesPath || "", "assets", "ece-tool-suite.ico"),
  ];
  return candidates.find((p) => {
    try { return fs.existsSync(p); } catch { return false; }
  });
}

// Dev layout only (source present). Rebuild if there's no build, or any source is newer.
function needsRendererBuild() {
  const srcDir = path.join(rendererDir(), "src");
  if (!fs.existsSync(srcDir)) return false;            // packaged: dist is prebuilt
  if (!fs.existsSync(devDistIndex())) return true;     // never built
  const built = mtime(devDistIndex());
  const newestSrc = Math.max(
    newestUnder(srcDir),
    mtime(path.join(rendererDir(), "index.html")),
    mtime(path.join(rendererDir(), "vite.config.ts")),
    mtime(path.join(rendererDir(), "tailwind.config.js")),
    mtime(path.join(rendererDir(), "package.json")),
  );
  return newestSrc > built;
}

function buildRenderer() {
  return new Promise((resolve) => {
    const npm = process.platform === "win32" ? "npm.cmd" : "npm";
    const proc = spawn(npm, ["run", "build"], {
      cwd: rendererDir(),
      stdio: "inherit",
      shell: process.platform === "win32",
    });
    proc.on("exit", (code) => resolve(code === 0));
    proc.on("error", () => resolve(false));
  });
}

const SPLASH = "data:text/html," + encodeURIComponent(`
<!doctype html><meta charset="utf-8"><style>
  html,body{height:100%;margin:0}
  body{display:grid;place-items:center;background:#0a0c10;color:#e7ecf3;
       font-family:'Segoe UI',system-ui,sans-serif}
  .box{text-align:center}
  .logo{width:44px;height:44px;border-radius:12px;margin:0 auto 16px;
        background:linear-gradient(135deg,#2dd4ea,#a78bfa)}
  .sp{width:26px;height:26px;margin:18px auto 0;border:3px solid #232a33;
      border-top-color:#2dd4ea;border-radius:50%;animation:s .8s linear infinite}
  @keyframes s{to{transform:rotate(360deg)}}
  h1{font-size:16px;margin:0 0 4px} p{color:#8b95a5;font-size:13px;margin:0}
</style><div class="box"><div class="logo"></div>
<h1>ECE Tool Suite</h1><p>Preparing the interface — one moment…</p>
<div class="sp"></div></div>`);

const errorPage = (title, detail) => "data:text/html," + encodeURIComponent(`
<!doctype html><meta charset="utf-8"><style>
  html,body{height:100%;margin:0}
  body{display:grid;place-items:center;background:#0a0c10;color:#e7ecf3;
       font-family:'Segoe UI',system-ui,sans-serif}
  .box{max-width:640px;padding:32px}
  h1{font-size:17px;margin:0 0 8px;color:#b91c1c}
  p{color:#8b95a5;font-size:13px;line-height:1.5}
  pre{background:#0f172a;color:#e2e8f0;font-size:11px;padding:12px;border-radius:8px;
      max-height:260px;overflow:auto;white-space:pre-wrap}
</style><div class="box"><h1>${title}</h1>
<p>${detail}</p></div>`);

function loadRenderer() {
  if (process.env.RENDERER_URL) return win.loadURL(process.env.RENDERER_URL);
  if (fs.existsSync(packagedIndex())) return win.loadFile(packagedIndex());
  if (fs.existsSync(devDistIndex())) return win.loadFile(devDistIndex());
  if (app.isPackaged) {
    // never point a packaged install at a dev server that cannot exist there
    return win.loadURL(errorPage("Interface files missing",
      "The packaged renderer (resources/renderer/dist) was not found — this build is incomplete. Re-run npm run dist."));
  }
  return win.loadURL("http://localhost:5173");
}

async function createWindow() {
  port = await findFreePort(PREFERRED_PORT);
  if (port !== PREFERRED_PORT) console.warn(`port ${PREFERRED_PORT} busy; backend on ${port}`);
  const s = spawnSidecar({ port, nonce: NONCE });
  sidecar = s.proc;
  let sidecarExit = null;
  s.proc.on("exit", (code) => { sidecarExit = code; });
  s.proc.on("error", (e) => { sidecarExit = `spawn error: ${e.message}`; });

  win = new BrowserWindow({
    width: 1480,
    height: 920,
    backgroundColor: "#0a0c10",
    icon: appIcon(),
    show: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Auto-build the UI if needed, showing a splash so the window is never blank.
  if (needsRendererBuild()) {
    win.loadURL(SPLASH);
    const ok = await buildRenderer();
    if (!ok) console.error("renderer auto-build failed; loading last good build if any");
  }

  // Backend can come up in parallel with the build; make sure it's healthy before we load.
  try {
    await waitForHealth(s.baseUrl, { timeoutMs: 30000, nonce: NONCE });
  } catch (e) {
    console.error("backend failed to become healthy:", e.message);
    // A dead backend must be REPORTED, not papered over with a normal-looking UI whose
    // every call silently fails. Show the sidecar's own output so the cause is visible.
    const tail = s.outputTail() || "(no output captured)";
    const why = sidecarExit !== null ? `The backend process exited (${sidecarExit}).`
                                     : "The backend did not answer /health in time.";
    win.loadURL(errorPage("Backend failed to start",
      `${why} Python: ${s.python}<br><br><pre>${tail
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")}</pre>`));
    return;
  }

  // Log renderer load failures (e.g. bad asset paths); the window is left as-is.
  win.webContents.on("did-fail-load", (_e, code, desc, url) => {
    if (code === -3) return; // aborted (normal during redirects)
    console.error("renderer failed to load:", code, desc, url);
  });

  loadRenderer();
}

app.whenReady().then(createWindow);
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
app.on("window-all-closed", () => {
  if (sidecar) sidecar.kill();
  if (process.platform !== "darwin") app.quit();
});
app.on("before-quit", () => {
  if (sidecar) sidecar.kill();
});

ipcMain.handle("backend-port", () => port);
ipcMain.handle("open-external", (_e, url) => {
  if (typeof url === "string" && /^https?:\/\//.test(url)) shell.openExternal(url);
});
