/**
 * Evenly spaced x-axis ticks on 1 January of whole years, for a time axis in epoch milliseconds.
 * Returns an empty list when the span is too short to place at least two ticks, in which case the
 * chart falls back to its automatic ticks.
 */
export function yearTicks(minT: number, maxT: number, target = 8): number[] {
  if (!Number.isFinite(minT) || !Number.isFinite(maxT) || maxT <= minT) return [];
  const y0 = new Date(minT).getUTCFullYear();
  const y1 = new Date(maxT).getUTCFullYear();
  const span = y1 - y0;
  const step = [1, 2, 5, 10, 20, 25, 50, 100].find((s) => span / s <= target) ?? 100;
  const ticks: number[] = [];
  for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) {
    const t = Date.UTC(y, 0, 1);
    if (t >= minT && t <= maxT) ticks.push(t);
  }
  return ticks.length >= 2 ? ticks : [];
}

export const yearLabel = (t: number): string => String(new Date(t).getUTCFullYear());

/**
 * Epoch milliseconds for an API timestamp, always interpreted as UTC. The API emits either a plain
 * date (YYYY-MM-DD, already UTC) or a zone-less date-time; browsers would read the latter as local
 * time, which can move a point across a year boundary on the axis.
 */
export function toEpoch(iso: string): number {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(iso);
  return new Date(iso.length > 10 && !hasZone ? `${iso}Z` : iso).getTime();
}
