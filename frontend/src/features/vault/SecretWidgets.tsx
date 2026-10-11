import { useEffect, useState } from "react";

import { Alert, Badge, Button, Checkbox, Dialog, Field, Input } from "@/components/ui";
import type { Credential } from "@/types/api";

import { CLEAR_AFTER_MS } from "./clipboard";
import { DEFAULT_OPTIONS, generatePassword, MAX_LENGTH, MIN_LENGTH, type GeneratorOptions } from "./passwordGenerator";
import { estimateEntropyBits, STRENGTH_TEXT, STRENGTH_TONE, strengthLabel } from "./strength";

export const REVEAL_SECONDS = 30;

// --------------------------------------------------------------------------- strength meter

const SEGMENTS = ["very_weak", "weak", "fair", "strong", "very_strong"] as const;
const segmentColor = { red: "bg-red-500", amber: "bg-amber-500", blue: "bg-blue-500", green: "bg-green-600" } as const;

export function StrengthMeter({ password }: { password: string }) {
  if (!password) return null;
  const bits = estimateEntropyBits(password);
  const label = strengthLabel(bits);
  const filled = SEGMENTS.indexOf(label) + 1;
  return (
    <div className="mt-2" aria-live="polite">
      <div className="flex gap-1" aria-hidden="true">
        {SEGMENTS.map((segment, index) => (
          <span key={segment} className={`h-1.5 flex-1 rounded ${index < filled ? segmentColor[STRENGTH_TONE[label]] : "bg-slate-200"}`} />
        ))}
      </div>
      <p className="mt-1 text-xs text-slate-600">
        Strength: <strong>{STRENGTH_TEXT[label]}</strong> · about {Math.round(bits)} bits (an estimate: it cannot detect every dictionary word or leaked password)
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------- generator

export function PasswordGenerator({ initialLength, onGenerate }: { initialLength: number; onGenerate: (password: string) => void }) {
  const [options, setOptions] = useState<GeneratorOptions>({ ...DEFAULT_OPTIONS, length: Math.max(DEFAULT_OPTIONS.length, initialLength) });
  const [error, setError] = useState<string | null>(null);
  const toggle = (key: keyof Omit<GeneratorOptions, "length">) => setOptions((o) => ({ ...o, [key]: !o[key] }));

  const generate = () => {
    try {
      setError(null);
      onGenerate(generatePassword(options));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not generate a password.");
    }
  };

  return (
    <fieldset className="rounded-md border border-slate-200 p-3">
      <legend className="px-1 text-xs font-medium text-slate-600">Password generator (runs in your browser)</legend>
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-28">
          <Field label="Length">
            {(props) => (
              <Input
                {...props}
                type="number"
                min={MIN_LENGTH}
                max={MAX_LENGTH}
                value={options.length}
                onChange={(e) => setOptions((o) => ({ ...o, length: Number(e.target.value) }))}
              />
            )}
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          <Checkbox label="a-z" checked={options.lower} onChange={() => toggle("lower")} />
          <Checkbox label="A-Z" checked={options.upper} onChange={() => toggle("upper")} />
          <Checkbox label="0-9" checked={options.digits} onChange={() => toggle("digits")} />
          <Checkbox label="Symbols" checked={options.symbols} onChange={() => toggle("symbols")} />
          <Checkbox label="Avoid look-alikes (0 O 1 l)" checked={options.avoidAmbiguous} onChange={() => toggle("avoidAmbiguous")} />
        </div>
        <Button variant="secondary" onClick={generate}>
          Generate
        </Button>
      </div>
      {error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
    </fieldset>
  );
}

// --------------------------------------------------------------------------- reveal dialog

/**
 * Shows a decrypted secret that the parent obtained from a user click. The secret lives only in the parent's
 * local state; this dialog closes (and the parent drops it) after REVEAL_SECONDS or on Escape/close.
 */
export function SecretDialog({ title, secret, multiline, onClose }: { title: string; secret: string | null; multiline?: boolean; onClose: () => void }) {
  const [hidden, setHidden] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(REVEAL_SECONDS);

  useEffect(() => {
    if (secret === null) return;
    setHidden(false);
    setSecondsLeft(REVEAL_SECONDS);
    const tick = setInterval(() => setSecondsLeft((s) => s - 1), 1000);
    const close = setTimeout(onClose, REVEAL_SECONDS * 1000);
    return () => {
      clearInterval(tick);
      clearTimeout(close);
    };
  }, [secret, onClose]);

  return (
    <Dialog open={secret !== null} title={title} onClose={onClose}>
      <div className="space-y-4">
        {multiline ? (
          <pre aria-label="Secret value" className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-md bg-slate-900 p-3 font-mono text-sm text-slate-50">
            {hidden ? "••••••••••••" : secret}
          </pre>
        ) : (
          <output aria-label="Secret value" className="block break-all rounded-md bg-slate-900 px-3 py-3 font-mono text-base text-slate-50">
            {hidden ? "••••••••••••" : secret}
          </output>
        )}
        <p className="text-xs text-slate-500" aria-live="polite">
          This closes automatically in {Math.max(secondsLeft, 0)} s. The reveal was recorded in the audit log.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setHidden((h) => !h)}>
            {hidden ? "Show" : "Hide"}
          </Button>
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    </Dialog>
  );
}

// --------------------------------------------------------------------------- clipboard notice

export function ClipboardNotice({ state, onDismiss }: { state: "copied" | "cleared" | null; onDismiss: () => void }) {
  if (!state) return null;
  return (
    <Alert
      tone={state === "copied" ? "info" : "success"}
      className="mb-4"
      action={
        <Button variant="ghost" size="sm" onClick={onDismiss}>
          Dismiss
        </Button>
      }
    >
      {state === "copied"
        ? `Copied. SecureVault will try to clear your clipboard in ${CLEAR_AFTER_MS / 1000} seconds. Clearing is best-effort: browser permissions, clipboard managers or copying something else can prevent it.`
        : "Clipboard cleared, if your browser allowed it. Clipboard history tools may still hold a copy."}
    </Alert>
  );
}

// --------------------------------------------------------------------------- hygiene badges

export function HygieneBadges({ credential }: { credential: Credential }) {
  return (
    <div className="flex flex-wrap gap-1">
      <Badge tone={STRENGTH_TONE[credential.strength]}>{STRENGTH_TEXT[credential.strength]}</Badge>
      {credential.is_expired && <Badge tone="red">Expired</Badge>}
      {credential.expires_soon && <Badge tone="amber">Expires soon</Badge>}
      {credential.reuse_count > 0 && <Badge tone="amber">Reused ×{credential.reuse_count + 1}</Badge>}
    </div>
  );
}
