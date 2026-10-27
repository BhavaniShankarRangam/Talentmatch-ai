/**
 * Score display. Never round in a way that could change apparent filter eligibility:
 * values with 2 or fewer decimals show 2 decimals; anything finer shows the full stored
 * precision (4 decimals). e.g. 97.995 -> "97.9950", never "98.00".
 */
export function formatScore(exact: string | null | undefined): string {
  if (exact === null || exact === undefined) return "—";
  const [whole, frac = ""] = exact.split(".");
  const f = frac.padEnd(4, "0");
  return f.slice(2) === "00" ? `${whole}.${f.slice(0, 2)}` : `${whole}.${f}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ");
}

/** Validate a score bound typed by the user. Returns an error message or null. */
export function scoreBoundError(label: string, raw: string): string | null {
  if (raw.trim() === "") return null;
  if (!/^\d{1,3}(\.\d{1,4})?$/.test(raw.trim())) return `${label} must be a number with at most 4 decimals.`;
  const n = Number(raw);
  if (n < 0 || n > 100) return `${label} must be between 0 and 100.`;
  return null;
}
