import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { Alert, Button, Field, Input } from "@/components/ui";
import { api, ApiError, fieldErrors } from "@/services/api";

import { AuthLayout } from "./AuthLayout";
import { useFragmentToken } from "./useFragmentToken";

const passwordRule = z.string().min(12, "Use at least 12 characters.").max(256);

const newPasswordSchema = z
  .object({ password: passwordRule, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match." });
type NewPasswordForm = z.infer<typeof newPasswordSchema>;

function messageFor(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
}

// --------------------------------------------------------------------------- forgot password

const emailSchema = z.object({ email: z.string().min(1, "Enter your email.").email("Enter a valid email address.") });

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof emailSchema>>({ resolver: zodResolver(emailSchema) });

  const submit = form.handleSubmit(async ({ email }) => {
    setError(null);
    try {
      await api.post("/auth/password-reset/", { email }, { skipUnauthorizedHandler: true });
      setSent(true);
    } catch (e) {
      setError(messageFor(e));
    }
  });

  return (
    <AuthLayout title="Reset your password" subtitle="We will email a reset link if the account exists.">
      {sent ? (
        <div className="space-y-4">
          <Alert tone="success">If an account exists for that email, a reset link has been sent. It expires in 30 minutes.</Alert>
          <Link to="/login" className="text-sm text-brand-700 hover:underline">
            Back to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} noValidate className="space-y-4">
          {error && <Alert tone="error">{error}</Alert>}
          <Field label="Email" error={form.formState.errors.email?.message}>
            {(props) => <Input {...props} type="email" autoComplete="username" autoFocus {...form.register("email")} />}
          </Field>
          <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
            Send reset link
          </Button>
          <p className="text-center text-sm">
            <Link to="/login" className="text-brand-700 hover:underline">
              Back to sign in
            </Link>
          </p>
        </form>
      )}
    </AuthLayout>
  );
}

// --------------------------------------------------------------------------- token + new password

function NewPasswordForm({ endpoint, token, submitLabel, successMessage }: { endpoint: string; token: string; submitLabel: string; successMessage: string }) {
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<NewPasswordForm>({ resolver: zodResolver(newPasswordSchema) });

  const submit = form.handleSubmit(async ({ password }) => {
    setError(null);
    try {
      await api.post(endpoint, { token, password }, { skipUnauthorizedHandler: true });
      setDone(true);
    } catch (e) {
      const fields = fieldErrors(e);
      if (e instanceof ApiError && e.code === "weak_password" && e.details?.password) {
        form.setError("password", { message: e.details.password.join(" ") });
      } else if (fields.password) {
        form.setError("password", { message: fields.password });
      } else {
        setError(messageFor(e));
      }
    }
  });

  if (done) {
    return (
      <div className="space-y-4">
        <Alert tone="success">{successMessage}</Alert>
        <Link to="/login" className="text-sm font-medium text-brand-700 hover:underline">
          Go to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <Field label="New password" hint="At least 12 characters. Avoid common or personal words." error={form.formState.errors.password?.message}>
        {(props) => <Input {...props} type="password" autoComplete="new-password" autoFocus {...form.register("password")} />}
      </Field>
      <Field label="Confirm new password" error={form.formState.errors.confirm?.message}>
        {(props) => <Input {...props} type="password" autoComplete="new-password" {...form.register("confirm")} />}
      </Field>
      <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
        {submitLabel}
      </Button>
    </form>
  );
}

function MissingToken({ what }: { what: string }) {
  return (
    <div className="space-y-4">
      <Alert tone="error">This {what} link is missing or incomplete. Open the full link you were given.</Alert>
      <Link to="/login" className="text-sm text-brand-700 hover:underline">
        Back to sign in
      </Link>
    </div>
  );
}

export function ResetPasswordPage() {
  const token = useFragmentToken();
  return (
    <AuthLayout title="Choose a new password" subtitle="This signs you out of every other device.">
      {token ? (
        <NewPasswordForm endpoint="/auth/password-reset/confirm/" token={token} submitLabel="Update password" successMessage="Password updated. Sign in with your new password." />
      ) : (
        <MissingToken what="password reset" />
      )}
    </AuthLayout>
  );
}

export function AcceptInvitePage() {
  const token = useFragmentToken();
  return (
    <AuthLayout title="Activate your account" subtitle="Choose a password to finish setting up SecureVault.">
      {token ? (
        <NewPasswordForm endpoint="/auth/invitations/accept/" token={token} submitLabel="Activate account" successMessage="Account activated. You can now sign in." />
      ) : (
        <MissingToken what="invitation" />
      )}
    </AuthLayout>
  );
}
