// Single source of truth for turning the messy scraped `position` strings
// (mix of abbreviations like "SF", full names like "Small Forward", and
// generic/combo labels like "Combo Guard") into a consistent display value.
//
// Canonical set is PG / SG / SF / PF / C. Generic or combo roles that don't
// map cleanly to one spot fall back to "G" / "F" rather than guessing a
// specific position; anything unrecognized becomes "—".

const DIRECT: Record<string, string> = {
  PG: "PG",
  SG: "SG",
  SF: "SF",
  PF: "PF",
  C: "C",
  "POINT GUARD": "PG",
  "SHOOTING GUARD": "SG",
  "SMALL FORWARD": "SF",
  "POWER FORWARD": "PF",
  CENTER: "C",
};

export function normalizePosition(raw: string | null | undefined): string {
  if (!raw) return "—";
  const s = raw.trim().toUpperCase();
  if (!s || s === "UNKNOWN" || s === "UNKNOWN POSITION" || s === "N/A") return "—";

  // Slash/comma forms ("PG/SG", "SF, PF") — take the primary (first) token as
  // the best-fit position.
  const primary = s.split(/[/,]/)[0].trim();

  if (DIRECT[primary]) return DIRECT[primary];

  // Generic / combo fallbacks (honest — no guessing into a specific spot).
  if (primary === "G" || primary.includes("GUARD")) return "G"; // Combo Guard, Guard
  if (primary === "F" || primary.includes("FORWARD") || primary === "WING") return "F";
  if (primary.startsWith("CENT")) return "C";

  return "—";
}
