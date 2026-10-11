import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useLocation } from "react-router-dom";
import { z } from "zod";

import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/services/api";

import { AuthLayout } from "./AuthLayout";
import { useAuth } from "./AuthContext";

const credentialsSchema = z.object({
  email: z.string().min(1, "Enter your email.").email("Enter a valid email address."),
  password: z.string().min(1, "Enter your password."),
});
const codeSchema = z.object({ code: z.string().trim().min(6, "Enter the 6-digit code or a recovery code.") });

type Credentials = z.infer<typeof credentialsSchema>;
type CodeForm = z.infer<typeof codeSchema>;

function safeNext(state: unknown): string {
  const from = (state as { from?: string } | null)?.from;
  // Only same-app paths: never redirect to an attacker-supplied absolute URL.
  return from && from.startsWith("/") && !from.startsWith("//") ? from : "/";
}

const SIGN_OUT_TEXT = {
  session_ended: "Your session ended (for example, your account or device was suspended). Please sign in again.",
  lockdown: "You were signed out because the security team started an emergency lockdown. Sign-in may be refused until it is lifted.",
} as const;

export function LoginPage() {
  const { user, login, verifyMfa, signOutReason } = useAuth();
  const location = useLocation();
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [formError, setFormError] = useState<string | null>(null);

  const credentials = useForm<Credentials>({ resolver: zodResolver(credentialsSchema) });
  const code = useForm<CodeForm>({ resolver: zodResolver(codeSchema) });

  if (user) return <Navigate to={safeNext(location.state)} replace />;

  const describe = (error: unknown) =>
    error instanceof ApiError ? error.message : "Something went wrong. Please try again.";

  const submitCredentials = credentials.handleSubmit(async (values) => {
    setFormError(null);
    try {
      const result = await login(values.email, values.password);
      if (result.mfa_required) setStep("mfa");
    } catch (error) {
      setFormError(describe(error));
    }
  });

  const submitCode = code.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await verifyMfa(values.code);
    } catch (error) {
      if (error instanceof ApiError && error.code === "mfa_session_expired") {
        setStep("password");
        code.reset();
      }
      setFormError(describe(error));
    }
  });

  if (step === "mfa") {
    return (
      // key: without it React reuses the previous step's <input> DOM node, carrying the email over into the code field.
      <AuthLayout key="mfa-step" title="Two-step verification" subtitle="Enter the code from your authenticator app, or a recovery code.">
        <form onSubmit={submitCode} noValidate className="space-y-4">
          {formError && <Alert tone="error">{formError}</Alert>}
          <Field label="Verification code" error={code.formState.errors.code?.message}>
            {(props) => <Input {...props} autoComplete="one-time-code" inputMode="text" autoFocus {...code.register("code")} />}
          </Field>
          <Button type="submit" className="w-full" loading={code.formState.isSubmitting}>
            Verify
          </Button>
          <Button variant="ghost" className="w-full" onClick={() => { setStep("password"); setFormError(null); }}>
            Back to sign in
          </Button>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout key="password-step" title="Sign in" subtitle="Use your work account.">
      <form onSubmit={submitCredentials} noValidate className="space-y-4">
        {signOutReason && !formError && <Alert tone={signOutReason === "lockdown" ? "warning" : "info"}>{SIGN_OUT_TEXT[signOutReason]}</Alert>}
        {formError && <Alert tone="error">{formError}</Alert>}
        <Field label="Email" error={credentials.formState.errors.email?.message}>
          {(props) => <Input {...props} type="email" autoComplete="username" autoFocus {...credentials.register("email")} />}
        </Field>
        <Field label="Password" error={credentials.formState.errors.password?.message}>
          {(props) => <Input {...props} type="password" autoComplete="current-password" {...credentials.register("password")} />}
        </Field>
        <Button type="submit" className="w-full" loading={credentials.formState.isSubmitting}>
          Sign in
        </Button>
        <p className="text-center text-sm">
          <Link to="/forgot-password" className="text-brand-700 hover:underline">
            Forgot your password?
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}
