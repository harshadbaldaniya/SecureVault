import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Badge, Button, Card, Dialog, Field, Input, PageHeader } from "@/components/ui";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { TotpSetup } from "@/types/api";

import { useAuth } from "./AuthContext";

const message = (error: unknown) => (error instanceof ApiError ? error.message : "Something went wrong. Please try again.");

// --------------------------------------------------------------------------- recovery codes (shown once, memory only)

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return (
    <div className="space-y-4">
      <Alert tone="warning">
        Save these recovery codes somewhere safe, such as a password manager. Each works once, and they will not be shown again.
      </Alert>
      <ul className="grid grid-cols-2 gap-2 rounded-md bg-slate-50 p-4 font-mono text-sm" aria-label="Recovery codes">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <div className="flex justify-end">
        <Button onClick={onDone}>I have saved these codes</Button>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- MFA enrolment

const codeSchema = z.object({ code: z.string().trim().regex(/^\d{6}$/, "Enter the 6-digit code from your app.") });

function EnrolMfa({ onEnrolled }: { onEnrolled: (codes: string[]) => void }) {
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof codeSchema>>({ resolver: zodResolver(codeSchema) });

  const start = useMutation({
    mutationFn: () => api.post<TotpSetup>("/auth/mfa/totp/setup/"),
    onSuccess: setSetup,
    onError: (e) => setError(message(e)),
  });

  useEffect(() => {
    if (!setup) return;
    // Rendered locally: the secret never leaves this browser except to our own server.
    QRCode.toDataURL(setup.otpauth_uri, { margin: 1, width: 192 }).then(setQr).catch(() => setQr(null));
  }, [setup]);

  const confirm = form.handleSubmit(async ({ code }) => {
    setError(null);
    try {
      const result = await api.post<{ recovery_codes: string[] }>("/auth/mfa/totp/confirm/", { code });
      setSetup(null);
      setQr(null);
      onEnrolled(result.recovery_codes);
    } catch (e) {
      setError(message(e));
    }
  });

  if (!setup) {
    return (
      <div className="space-y-3">
        {error && <Alert tone="error">{error}</Alert>}
        <Button onClick={() => { setError(null); start.mutate(); }} loading={start.isPending}>
          Set up authenticator app
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={confirm} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <p className="text-sm text-slate-600">Scan this QR code with an authenticator app (such as Google Authenticator, Microsoft Authenticator or Aegis), then enter the 6-digit code it shows.</p>
      {qr && <img src={qr} alt="QR code for your authenticator app" width={192} height={192} className="rounded border border-slate-200" />}
      <details className="text-sm">
        <summary className="cursor-pointer text-slate-600">Cannot scan? Enter the key manually</summary>
        <code className="mt-2 block break-all rounded bg-slate-100 p-2 font-mono">{setup.secret}</code>
      </details>
      <Field label="Verification code" error={form.formState.errors.code?.message}>
        {(props) => <Input {...props} inputMode="numeric" autoComplete="one-time-code" maxLength={6} {...form.register("code")} />}
      </Field>
      <Button type="submit" loading={form.formState.isSubmitting}>
        Turn on two-step verification
      </Button>
    </form>
  );
}

// --------------------------------------------------------------------------- re-authenticated actions

const reauthSchema = z.object({ password: z.string().min(1, "Enter your password."), code: z.string().trim().min(6, "Enter a code from your app.") });

function ReauthDialog({ open, title, confirmLabel, danger, onClose, onSubmit }: { open: boolean; title: string; confirmLabel: string; danger?: boolean; onClose: () => void; onSubmit: (values: z.infer<typeof reauthSchema>) => Promise<void> }) {
  const form = useForm<z.infer<typeof reauthSchema>>({ resolver: zodResolver(reauthSchema) });
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    form.reset();
    setError(null);
    onClose();
  };

  const submit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      await onSubmit(values);
      form.reset();
    } catch (e) {
      setError(message(e));
    }
  });

  return (
    <Dialog open={open} title={title} onClose={close}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <p className="text-sm text-slate-600">For your security, confirm your password and a current code.</p>
        {error && <Alert tone="error">{error}</Alert>}
        <Field label="Password" error={form.formState.errors.password?.message}>
          {(props) => <Input {...props} type="password" autoComplete="current-password" {...form.register("password")} />}
        </Field>
        <Field label="Authenticator or recovery code" error={form.formState.errors.code?.message}>
          {(props) => <Input {...props} autoComplete="one-time-code" {...form.register("code")} />}
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" variant={danger ? "danger" : "primary"} loading={form.formState.isSubmitting}>
            {confirmLabel}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// --------------------------------------------------------------------------- password change

const changeSchema = z
  .object({ current_password: z.string().min(1, "Enter your current password."), new_password: z.string().min(12, "Use at least 12 characters."), confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "Passwords do not match." });

function ChangePassword() {
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof changeSchema>>({ resolver: zodResolver(changeSchema) });

  const submit = form.handleSubmit(async ({ current_password, new_password }) => {
    setError(null);
    setDone(false);
    try {
      await api.post("/auth/password/change/", { current_password, new_password });
      form.reset();
      setDone(true);
    } catch (e) {
      const fields = fieldErrors(e);
      if (e instanceof ApiError && e.code === "weak_password" && e.details?.password) {
        form.setError("new_password", { message: e.details.password.join(" ") });
      } else if (fields.new_password) {
        form.setError("new_password", { message: fields.new_password });
      } else {
        setError(message(e));
      }
    }
  });

  return (
    <form onSubmit={submit} noValidate className="max-w-md space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      {done && <Alert tone="success">Password changed. You were signed out of all other devices.</Alert>}
      <Field label="Current password" error={form.formState.errors.current_password?.message}>
        {(props) => <Input {...props} type="password" autoComplete="current-password" {...form.register("current_password")} />}
      </Field>
      <Field label="New password" error={form.formState.errors.new_password?.message}>
        {(props) => <Input {...props} type="password" autoComplete="new-password" {...form.register("new_password")} />}
      </Field>
      <Field label="Confirm new password" error={form.formState.errors.confirm?.message}>
        {(props) => <Input {...props} type="password" autoComplete="new-password" {...form.register("confirm")} />}
      </Field>
      <Button type="submit" loading={form.formState.isSubmitting}>
        Change password
      </Button>
    </form>
  );
}

// --------------------------------------------------------------------------- page

export function SecurityPage() {
  const { user, refresh } = useAuth();
  const [codes, setCodes] = useState<string[] | null>(null);
  const [dialog, setDialog] = useState<"disable" | "regenerate" | null>(null);
  if (!user) return null;

  const enrolled = async (recoveryCodes: string[]) => {
    setCodes(recoveryCodes);
    await refresh();
  };

  return (
    <>
      <PageHeader title="Account security" description="Protect your account with two-step verification and a strong password." />
      <div className="space-y-6">
        {user.mfa_enrollment_required && (
          <Alert tone="warning">Your organization requires two-step verification. Set it up now to continue using SecureVault.</Alert>
        )}

        <Card title="Two-step verification" description="Require a code from an authenticator app when you sign in." actions={<Badge tone={user.mfa_enabled ? "green" : "amber"}>{user.mfa_enabled ? "On" : "Off"}</Badge>}>
          {codes ? (
            <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />
          ) : user.mfa_enabled ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => setDialog("regenerate")}>
                Generate new recovery codes
              </Button>
              <Button variant="danger" onClick={() => setDialog("disable")}>
                Turn off
              </Button>
            </div>
          ) : (
            <EnrolMfa onEnrolled={enrolled} />
          )}
        </Card>

        <Card title="Change password" description="You will stay signed in here; other devices are signed out.">
          <ChangePassword />
        </Card>
      </div>

      <ReauthDialog
        open={dialog === "disable"}
        title="Turn off two-step verification"
        confirmLabel="Turn off"
        danger
        onClose={() => setDialog(null)}
        onSubmit={async (values) => {
          await api.post("/auth/mfa/totp/disable/", values);
          setDialog(null);
          await refresh();
        }}
      />
      <ReauthDialog
        open={dialog === "regenerate"}
        title="Generate new recovery codes"
        confirmLabel="Generate"
        onClose={() => setDialog(null)}
        onSubmit={async (values) => {
          const result = await api.post<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes/", values);
          setDialog(null);
          setCodes(result.recovery_codes);
        }}
      />
    </>
  );
}
