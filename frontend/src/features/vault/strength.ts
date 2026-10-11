/**
 * Heuristic password-strength estimate. A port of backend/apps/vault/strength.py; both are checked
 * against shared/strength-vectors.json so the live meter matches what the server stores.
 *
 * It is an ESTIMATE: it cannot know leaked passwords, personal information or ordinary dictionary words,
 * so it can overestimate. It nudges users; it is never a security gate.
 */

const COMMON_PASSWORDS = new Set([
  "password", "passw0rd", "123456", "1234567", "12345678", "123456789", "1234567890", "qwerty", "qwertyuiop",
  "letmein", "welcome", "admin", "administrator", "iloveyou", "monkey", "dragon", "abc123", "password1",
  "111111", "sunshine", "princess", "football", "login", "secret", "master", "changeme", "default",
]);

const COMMON_WORD_MIN_LENGTH = 5;
// Longest first, then alphabetical: the same fixed order the backend uses.
const COMMON_WORDS_BY_PRIORITY = [...COMMON_PASSWORDS]
  .filter((word) => word.length >= COMMON_WORD_MIN_LENGTH)
  .sort((a, b) => b.length - a.length || (a < b ? -1 : a > b ? 1 : 0));

const SYMBOL_POOL = 33;
const OTHER_POOL = 64;

export type StrengthLabel = "very_weak" | "weak" | "fair" | "strong" | "very_strong";

const LABELS: Array<[number, StrengthLabel]> = [
  [28, "very_weak"],
  [36, "weak"],
  [60, "fair"],
  [80, "strong"],
];

const isAscii = (char: string) => char.charCodeAt(0) < 128;
const isLower = (char: string) => char >= "a" && char <= "z";
const isUpper = (char: string) => char >= "A" && char <= "Z";
const isDigit = (char: string) => char >= "0" && char <= "9";

function poolSize(chars: string[]): number {
  let pool = 0;
  if (chars.some((c) => isLower(c))) pool += 26;
  if (chars.some((c) => isUpper(c))) pool += 26;
  if (chars.some((c) => isDigit(c))) pool += 10;
  if (chars.some((c) => isAscii(c) && !isLower(c) && !isUpper(c) && !isDigit(c))) pool += SYMBOL_POOL;
  if (chars.some((c) => !isAscii(c))) pool += OTHER_POOL;
  return pool;
}

export function estimateEntropyBits(password: string): number {
  if (!password) return 0;
  const lowered = password.toLowerCase();
  if (COMMON_PASSWORDS.has(lowered)) return 4;

  const chars = Array.from(password); // by code point, like Python
  const pool = poolSize(chars);
  let effective = 0;
  let previous: string | null = null;
  let step = 0;
  for (const char of chars) {
    if (previous === null) {
      effective += 1;
    } else if (char !== previous) {
      const delta = (char.codePointAt(0) ?? 0) - (previous.codePointAt(0) ?? 0);
      if ((delta === 1 || delta === -1) && (step === 0 || step === delta)) {
        step = delta;
      } else {
        step = 0;
        effective += 1;
      }
    }
    previous = char;
  }

  for (const word of COMMON_WORDS_BY_PRIORITY) {
    if (lowered.includes(word) && word !== lowered) {
      effective -= word.length - 1;
      break;
    }
  }

  effective = Math.max(effective, 1);
  const bits = effective * Math.log2(Math.max(pool, 2));
  return Math.round(bits * 10) / 10;
}

export function strengthLabel(bits: number): StrengthLabel {
  for (const [ceiling, label] of LABELS) if (bits < ceiling) return label;
  return "very_strong";
}

export const STRENGTH_TEXT: Record<StrengthLabel, string> = {
  very_weak: "Very weak",
  weak: "Weak",
  fair: "Fair",
  strong: "Strong",
  very_strong: "Very strong",
};

export const STRENGTH_TONE: Record<StrengthLabel, "red" | "amber" | "blue" | "green"> = {
  very_weak: "red",
  weak: "red",
  fair: "amber",
  strong: "green",
  very_strong: "green",
};
