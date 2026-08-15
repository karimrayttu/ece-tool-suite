// Autoscaled polyline for live instrument traces. Capture arrays run to hundreds of
// thousands of samples, so the min/max scan is an explicit loop — Math.min(...values)
// passes every sample as an argument and blows the call stack on a real capture.

export function drawTrace(
  ctx: CanvasRenderingContext2D,
  values: number[],
  width: number,
  height: number,
  color: string,
  padFrac = 0.15,
  padFloor = 0.1,
): { min: number; max: number } {
  let mn = Infinity, mx = -Infinity;
  for (const x of values) { if (x < mn) mn = x; if (x > mx) mx = x; }
  const pad = (mx - mn) * padFrac || padFloor;
  mn -= pad; mx += pad;
  ctx.strokeStyle = color; ctx.lineWidth = 1.4; ctx.beginPath();
  for (let i = 0; i < values.length; i++) {
    const x = (i / (values.length - 1)) * width;
    const y = height - ((values[i] - mn) / (mx - mn)) * height;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.stroke();
  return { min: mn, max: mx };
}
