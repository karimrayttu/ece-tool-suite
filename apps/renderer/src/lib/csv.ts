// Trigger a client-side CSV download from in-memory rows (no backend round-trip, so it
// never contends with the instrument's VISA session).

function esc(x: string | number): string {
  const s = String(x);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function downloadCsv(filename: string, headers: string[], rows: (string | number)[][]): void {
  const body = [headers.join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
  downloadBlob(filename, new Blob([body], { type: "text/csv;charset=utf-8" }));
}

export function stamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

export function downloadCanvasPng(canvas: HTMLCanvasElement | null, filename: string): void {
  if (!canvas) return;
  canvas.toBlob((blob) => {
    if (!blob) return;
    downloadBlob(filename, blob);
  }, "image/png");
}
