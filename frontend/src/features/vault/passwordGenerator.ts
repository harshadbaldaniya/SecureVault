/**
 * Password generator using the browser's CSPRNG (crypto.getRandomValues). Generated passwords never
 * leave the browser until the user saves the credential. No Math.random anywhere.
 */

export interface GeneratorOptions {
  length: number;
  lower: boolean;
  upper: boolean;
  digits: boolean;
  symbols: boolean;
  /** Drop look-alike characters (0 O o 1 l I |). */
  avoidAmbiguous: boolean;
}

export const MIN_LENGTH = 8;
export const MAX_LENGTH = 128;

const LOWER = "abcdefghijklmnopqrstuvwxyz";
const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const DIGITS = "0123456789";
const SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/~";
const AMBIGUOUS = new Set("0Oo1lI|".split(""));

export type RandomSource = (array: Uint32Array<ArrayBuffer>) => Uint32Array<ArrayBuffer>;
const defaultSource: RandomSource = (array) => crypto.getRandomValues(array);

/** Uniform integer in [0, max) by rejection sampling, so there is no modulo bias. */
export function randomInt(max: number, source: RandomSource = defaultSource): number {
  if (!Number.isInteger(max) || max <= 0 || max > 2 ** 32) throw new RangeError("max must be an integer in 1..2^32");
  const limit = Math.floor(2 ** 32 / max) * max; // largest multiple of max that fits in 32 bits
  const buffer = new Uint32Array(1);
  for (;;) {
    const value = source(buffer)[0] ?? 0;
    if (value < limit) return value % max;
  }
}

function pick(chars: string[], source: RandomSource): string {
  return chars[randomInt(chars.length, source)] as string;
}

function classes(options: GeneratorOptions): string[][] {
  const filter = (chars: string) => [...chars].filter((c) => !(options.avoidAmbiguous && AMBIGUOUS.has(c)));
  const result: string[][] = [];
  if (options.lower) result.push(filter(LOWER));
  if (options.upper) result.push(filter(UPPER));
  if (options.digits) result.push(filter(DIGITS));
  if (options.symbols) result.push(filter(SYMBOLS));
  return result;
}

export function generatePassword(options: GeneratorOptions, source: RandomSource = defaultSource): string {
  const pools = classes(options);
  if (pools.length === 0) throw new Error("Select at least one character type.");
  if (!Number.isInteger(options.length) || options.length < Math.max(MIN_LENGTH, pools.length) || options.length > MAX_LENGTH) {
    throw new RangeError(`Length must be between ${Math.max(MIN_LENGTH, pools.length)} and ${MAX_LENGTH}.`);
  }

  const all = pools.flat();
  // One guaranteed character from every selected class, the rest from the union, then a CSPRNG shuffle.
  const chars = pools.map((pool) => pick(pool, source));
  while (chars.length < options.length) chars.push(pick(all, source));
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randomInt(i + 1, source);
    [chars[i], chars[j]] = [chars[j] as string, chars[i] as string];
  }
  return chars.join("");
}

export const DEFAULT_OPTIONS: GeneratorOptions = {
  length: 20,
  lower: true,
  upper: true,
  digits: true,
  symbols: true,
  avoidAmbiguous: false,
};
