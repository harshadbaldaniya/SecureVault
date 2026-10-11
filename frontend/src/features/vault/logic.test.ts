import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import vectors from "../../../../shared/strength-vectors.json";
import type { SecurityPolicy } from "@/types/api";

import { copySecret } from "./clipboard";
import { parseTags, policyProblems } from "./CredentialForm";
import { DEFAULT_OPTIONS, generatePassword, randomInt, type RandomSource } from "./passwordGenerator";
import { estimateEntropyBits, strengthLabel } from "./strength";

describe("strength estimate", () => {
  it("matches the backend reference implementation on every shared vector", () => {
    expect(vectors.length).toBeGreaterThanOrEqual(30);
    for (const vector of vectors) {
      expect({ password: vector.password, bits: estimateEntropyBits(vector.password) }).toEqual({ password: vector.password, bits: vector.bits });
      expect(strengthLabel(estimateEntropyBits(vector.password))).toBe(vector.label);
    }
  });
});

describe("password generator", () => {
  it("uses the browser CSPRNG", () => {
    const spy = vi.spyOn(crypto, "getRandomValues");
    generatePassword(DEFAULT_OPTIONS);
    expect(spy).toHaveBeenCalled();
  });

  it("honours the length and includes every selected character class", () => {
    for (let i = 0; i < 200; i++) {
      const password = generatePassword({ ...DEFAULT_OPTIONS, length: 12 });
      expect(password).toHaveLength(12);
      expect(password).toMatch(/[a-z]/);
      expect(password).toMatch(/[A-Z]/);
      expect(password).toMatch(/\d/);
      expect(password).toMatch(/[^A-Za-z0-9]/);
    }
  });

  it("can avoid look-alike characters and restrict classes", () => {
    for (let i = 0; i < 200; i++) {
      const password = generatePassword({ ...DEFAULT_OPTIONS, length: 40, avoidAmbiguous: true });
      expect(password).not.toMatch(/[0Oo1lI|]/);
      expect(generatePassword({ length: 16, lower: false, upper: false, digits: true, symbols: false, avoidAmbiguous: false })).toMatch(/^\d{16}$/);
    }
  });

  it("produces different passwords every time", () => {
    const seen = new Set(Array.from({ length: 500 }, () => generatePassword(DEFAULT_OPTIONS)));
    expect(seen.size).toBe(500);
  });

  it("rejects impossible options", () => {
    expect(() => generatePassword({ ...DEFAULT_OPTIONS, lower: false, upper: false, digits: false, symbols: false })).toThrow(/at least one/);
    expect(() => generatePassword({ ...DEFAULT_OPTIONS, length: 7 })).toThrow(RangeError);
    expect(() => generatePassword({ ...DEFAULT_OPTIONS, length: 129 })).toThrow(RangeError);
    expect(() => generatePassword({ ...DEFAULT_OPTIONS, length: 12.5 })).toThrow(RangeError);
  });

  it("uses rejection sampling so there is no modulo bias", () => {
    // max = 3: limit = floor(2^32 / 3) * 3 = 4294967295. The value 4294967295 must be rejected.
    const values = [4294967295, 4294967294, 5];
    const source: RandomSource = (array) => {
      array[0] = values.shift() ?? 0;
      return array;
    };
    expect(randomInt(3, source)).toBe(4294967294 % 3); // first value rejected, second accepted
    expect(randomInt(3, source)).toBe(2);
  });

  it("is roughly uniform", () => {
    const counts = new Array(10).fill(0);
    for (let i = 0; i < 20000; i++) counts[randomInt(10)]++;
    for (const count of counts) expect(Math.abs(count - 2000)).toBeLessThan(200); // ~4.5 standard deviations
  });
});

describe("clipboard clearing (best effort)", () => {
  let clipboardText = "";
  let readAllowed = true;

  beforeEach(() => {
    vi.useFakeTimers();
    clipboardText = "";
    readAllowed = true;
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn(async (text: string) => {
          clipboardText = text;
        }),
        readText: vi.fn(async () => {
          if (!readAllowed) throw new DOMException("denied", "NotAllowedError");
          return clipboardText;
        }),
      },
    });
  });
  afterEach(() => vi.useRealTimers());

  it("clears the clipboard after 30 seconds when it still holds the secret", async () => {
    const cleared = vi.fn();
    await copySecret("s3cret", cleared);
    expect(clipboardText).toBe("s3cret");
    await vi.advanceTimersByTimeAsync(29_000);
    expect(clipboardText).toBe("s3cret");
    await vi.advanceTimersByTimeAsync(1_000);
    expect(clipboardText).toBe("");
    expect(cleared).toHaveBeenCalledOnce();
  });

  it("leaves a newer clipboard value alone", async () => {
    await copySecret("s3cret", vi.fn());
    clipboardText = "something the user copied later";
    await vi.advanceTimersByTimeAsync(30_000);
    expect(clipboardText).toBe("something the user copied later");
  });

  it("still tries to clear when the browser refuses to let us read the clipboard", async () => {
    await copySecret("s3cret", vi.fn());
    readAllowed = false;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(clipboardText).toBe("");
  });

  it("can be cancelled", async () => {
    const handle = await copySecret("s3cret", vi.fn());
    handle.cancel();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(clipboardText).toBe("s3cret");
  });
});

describe("form helpers", () => {
  const policy = { min_password_length: 14, require_uppercase: true, require_numbers: true, require_symbols: true } as SecurityPolicy;

  it("mirrors the server's password policy for PASSWORD secrets only", () => {
    expect(policyProblems(policy, "PASSWORD", "short")).toEqual([
      "Use at least 14 characters.",
      "Include an uppercase letter.",
      "Include a number.",
      "Include a symbol.",
    ]);
    expect(policyProblems(policy, "PASSWORD", "Xq7!Plaintext-Marker")).toEqual([]);
    expect(policyProblems(policy, "API_KEY", "abc")).toEqual([]);
  });

  it("normalises tags like the server", () => {
    expect(parseTags(" Prod, db ,prod,, Ops ")).toEqual(["prod", "db", "ops"]);
    expect(parseTags("")).toEqual([]);
  });
});
