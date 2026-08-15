// Packaging smoke test (headless): spawn the Python sidecar exactly as Electron would,
// confirm it binds localhost and serves a provenance-tagged /health, then shut it down.
//   dev layout:      node apps/desktop/smoke.js
//   packaged layout: set ECE_SUITE_RESOURCES=<...>\release\win-unpacked\resources first —
//     that forces sidecar.js onto resources\backend\runtime\python.exe, so the smoke
//     exercises the REAL bundled runtime instead of always passing via the dev venv.

const { spawnSidecar, waitForHealth } = require("./sidecar");

const PORT = Number(process.env.SMOKE_PORT || 8939);
const NONCE = `smoke-${Date.now()}`;

(async () => {
  const { proc, baseUrl, python, outputTail } = spawnSidecar({ port: PORT, nonce: NONCE });
  proc.on("exit", (code) => {
    if (code && code !== 0) console.error(`[sidecar exited ${code}]\n${outputTail()}`);
  });

  try {
    console.log(`spawning sidecar via ${python}`);
    const health = await waitForHealth(baseUrl, { timeoutMs: 25000, nonce: NONCE });

    const checks = [
      ["status ok", health.status === "ok"],
      ["launch nonce echoed (identity check)", health.nonce === NONCE],
      ["mode is hardware (no sim in runtime)", health.mode === "hardware"],
      ["all instrument roles start disconnected",
        Object.values(health.instruments || {}).every((i) => i.connected === false)],
      ["hardware NOT claimed connected", health.hardware_connected === false && health.any_connected === false],
      ["autonomous surface ⊆ chatbox surface",
        health.capabilities_autonomous.every((n) => health.capabilities_chatbox.includes(n))],
    ];

    console.log("health:", JSON.stringify(health, null, 2));
    let ok = true;
    for (const [label, pass] of checks) {
      console.log(`${pass ? "PASS" : "FAIL"}  ${label}`);
      ok = ok && pass;
    }
    proc.kill();
    process.exit(ok ? 0 : 1);
  } catch (e) {
    console.error("SMOKE FAILED:", e.message);
    console.error(outputTail());
    proc.kill();
    process.exit(1);
  }
})();
