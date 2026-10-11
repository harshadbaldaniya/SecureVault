import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Button, Card, Checkbox, Field, Input, PageHeader, PageLoader } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { SecurityPolicy } from "@/types/api";

const int = (min: number, max: number, label: string) =>
  z.coerce.number({ error: `Enter a number for ${label}.` }).int("Whole numbers only.").min(min, `Minimum is ${min}.`).max(max, `Maximum is ${max}.`);

const schema = z.object({
  min_password_length: int(8, 128, "minimum length"),
  require_uppercase: z.boolean(),
  require_numbers: z.boolean(),
  require_symbols: z.boolean(),
  max_password_age_days: int(0, 3650, "maximum age"),
  expiry_warning_days: int(0, 365, "warning period"),
  allow_view_once: z.boolean(),
  max_share_duration_days: int(1, 365, "share duration"),
  require_device_trust: z.boolean(),
  require_mfa: z.boolean(),
  block_on_high_risk: z.boolean(),
});
type FormInput = z.input<typeof schema>;
type FormOutput = z.output<typeof schema>;

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

function toForm(policy: SecurityPolicy): FormInput {
  const { id: _id, name: _name, updated_at: _updated, ...rest } = policy;
  return rest;
}

export function PolicyPage() {
  const { can, refresh } = useAuth();
  const canManage = can("policies.manage");
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = useQuery({ queryKey: ["policy"], queryFn: () => api.get<SecurityPolicy>("/policy/") });
  const form = useForm<FormInput, unknown, FormOutput>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (query.data) form.reset(toForm(query.data));
  }, [query.data, form]);

  const save = useMutation({
    mutationFn: (values: FormOutput) => api.patch<SecurityPolicy>("/policy/", values),
    onSuccess: async (policy) => {
      queryClient.setQueryData(["policy"], policy);
      setSaved(true);
      await refresh(); // require_mfa may change what this very user must do next
    },
    onError: (e) => {
      const fields = fieldErrors(e);
      const known = Object.keys(fields);
      if (known.length) known.forEach((name) => form.setError(name as keyof FormInput, { message: fields[name] ?? "Invalid value." }));
      else setError(message(e));
    },
  });

  if (query.isPending) return <PageLoader />;
  if (query.isError) return <Alert tone="error">{message(query.error)}</Alert>;

  const readOnly = !canManage;
  const err = form.formState.errors;

  return (
    <>
      <PageHeader title="Security policy" description="Organization-wide rules for credentials, sharing and access." />
      <form
        noValidate
        onSubmit={form.handleSubmit((values) => {
          setSaved(false);
          setError(null);
          save.mutate(values);
        })}
        className="space-y-6"
      >
        {readOnly && <Alert tone="info">You can view the policy but only administrators can change it.</Alert>}
        {error && <Alert tone="error">{error}</Alert>}
        {saved && <Alert tone="success">Policy saved. The change was recorded in the audit log.</Alert>}

        <Card title="Credential rules" description="Applied to secrets stored in the vault.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Minimum length" error={err.min_password_length?.message}>
              {(props) => <Input {...props} type="number" disabled={readOnly} {...form.register("min_password_length")} />}
            </Field>
            <Field label="Maximum age (days)" hint="0 means credentials never expire." error={err.max_password_age_days?.message}>
              {(props) => <Input {...props} type="number" disabled={readOnly} {...form.register("max_password_age_days")} />}
            </Field>
            <Field label="Expiry warning (days)" error={err.expiry_warning_days?.message}>
              {(props) => <Input {...props} type="number" disabled={readOnly} {...form.register("expiry_warning_days")} />}
            </Field>
          </div>
          <div className="mt-4 space-y-2">
            <Checkbox label="Require uppercase letters" disabled={readOnly} {...form.register("require_uppercase")} />
            <Checkbox label="Require numbers" disabled={readOnly} {...form.register("require_numbers")} />
            <Checkbox label="Require symbols" disabled={readOnly} {...form.register("require_symbols")} />
          </div>
        </Card>

        <Card title="Sharing" description="Enforced when credential sharing is enabled.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Maximum share duration (days)" error={err.max_share_duration_days?.message}>
              {(props) => <Input {...props} type="number" disabled={readOnly} {...form.register("max_share_duration_days")} />}
            </Field>
          </div>
          <div className="mt-4">
            <Checkbox label="Allow view-once sharing" disabled={readOnly} {...form.register("allow_view_once")} />
          </div>
        </Card>

        <Card title="Zero-trust access">
          <div className="space-y-2">
            <Checkbox label="Require multi-factor authentication for everyone" disabled={readOnly} {...form.register("require_mfa")} />
            <Checkbox label="Require a trusted device for sensitive operations" disabled={readOnly} {...form.register("require_device_trust")} />
            <Checkbox label="Pause a user's sensitive actions while a high-severity alert about them is open" disabled={readOnly} {...form.register("block_on_high_risk")} />
          </div>
          <p className="mt-3 text-xs text-slate-500">
            With device trust required, every device (including administrators' own) must be approved by another device administrator before it can reveal or change secrets. A sole administrator can use the server console command <code>approve_device</code> once.
          </p>
        </Card>

        {canManage && (
          <div className="flex justify-end">
            <Button type="submit" loading={save.isPending}>
              Save policy
            </Button>
          </div>
        )}
      </form>
    </>
  );
}
