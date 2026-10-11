import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Button, Field, Input, Select } from "@/components/ui";
import { api, ApiError, fieldErrors } from "@/services/api";
import type { Credential, Page, SecretType, SecurityPolicy, ServiceItem } from "@/types/api";

import { PasswordGenerator, StrengthMeter } from "./SecretWidgets";

const SYMBOLS = new Set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ ".split(""));
const TAG_PATTERN = /^[a-z0-9][a-z0-9 ._-]{0,39}$/;

/** Mirrors backend policy_violations(): the server is authoritative, this is early feedback. */
export function policyProblems(policy: SecurityPolicy, secretType: SecretType, secret: string): string[] {
  if (secretType !== "PASSWORD") return [];
  const problems: string[] = [];
  if (secret.length < policy.min_password_length) problems.push(`Use at least ${policy.min_password_length} characters.`);
  if (policy.require_uppercase && !/[A-Z]/.test(secret) && secret === secret.toLowerCase()) problems.push("Include an uppercase letter.");
  if (policy.require_numbers && !/\d/.test(secret)) problems.push("Include a number.");
  if (policy.require_symbols && ![...secret].some((c) => SYMBOLS.has(c))) problems.push("Include a symbol.");
  return problems;
}

export function parseTags(text: string): string[] {
  const tags: string[] = [];
  for (const raw of text.split(",")) {
    const tag = raw.trim().toLowerCase();
    if (tag && !tags.includes(tag)) tags.push(tag);
  }
  return tags;
}

function buildSchema(mode: "create" | "edit", policy: SecurityPolicy | undefined) {
  return z
    .object({
      title: z.string().trim().min(1, "Enter a title.").max(200),
      username: z.string().max(254),
      service: z.string(),
      secret_type: z.enum(["PASSWORD", "API_KEY", "OTHER"]),
      category: z.string().trim().max(40),
      tags: z.string(),
      expires_at: z.string(),
      password: z.string().max(4096, "Secrets are limited to 4096 characters."),
    })
    .superRefine((values, ctx) => {
      if (mode === "create" && !values.password) {
        ctx.addIssue({ code: "custom", path: ["password"], message: "Enter the secret to store." });
      }
      if (values.password && policy) {
        const problems = policyProblems(policy, values.secret_type, values.password);
        if (problems.length) ctx.addIssue({ code: "custom", path: ["password"], message: problems.join(" ") });
      }
      const tags = parseTags(values.tags);
      if (tags.length > 20) ctx.addIssue({ code: "custom", path: ["tags"], message: "Use at most 20 tags." });
      if (tags.some((t) => !TAG_PATTERN.test(t))) {
        ctx.addIssue({ code: "custom", path: ["tags"], message: "Tags may use letters, numbers, spaces, dots, dashes and underscores." });
      }
    });
}
type FormValues = z.infer<ReturnType<typeof buildSchema>>;

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function CredentialForm({ credential, onDone }: { credential: Credential | null; onDone: () => void }) {
  const mode = credential ? "edit" : "create";
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [showSecret, setShowSecret] = useState(false);

  const policy = useQuery({ queryKey: ["policy"], queryFn: () => api.get<SecurityPolicy>("/policy/") });
  const services = useQuery({
    queryKey: ["services", "options"],
    queryFn: () => api.get<Page<ServiceItem>>("/services/", { page_size: 100, status: "ACTIVE" }),
  });

  const schema = useMemo(() => buildSchema(mode, policy.data), [mode, policy.data]);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: credential?.title ?? "",
      username: credential?.username ?? "",
      service: credential?.service ?? "",
      secret_type: credential?.secret_type ?? "PASSWORD",
      category: credential?.category ?? "",
      tags: credential?.tags.join(", ") ?? "",
      expires_at: credential?.expires_at ?? "",
      password: "",
    },
  });
  const password = form.watch("password");
  const secretType = form.watch("secret_type");

  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const body: Record<string, unknown> = {
        title: values.title,
        username: values.username,
        service: values.service || null,
        secret_type: values.secret_type,
        category: values.category,
        tags: parseTags(values.tags),
      };
      if (!credential || values.expires_at !== (credential.expires_at ?? "")) body.expires_at = values.expires_at || null;
      if (values.password) body.password = values.password; // edit: blank means "keep the current secret"
      return credential ? api.patch<Credential>(`/vault/credentials/${credential.id}/`, body) : api.post<Credential>("/vault/credentials/", body);
    },
    // gcTime 0: do not keep the submitted variables (which include the secret) in the mutation cache.
    gcTime: 0,
    onSuccess: async () => {
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["credentials"] });
      onDone();
    },
    onError: (e) => {
      const fields = fieldErrors(e);
      const known = Object.keys(fields).filter((f) => f in form.getValues());
      if (known.length) known.forEach((f) => form.setError(f as keyof FormValues, { message: fields[f] ?? "Invalid value." }));
      else setError(message(e));
    },
  });

  const errors = form.formState.errors;
  const policyHint =
    policy.data && secretType === "PASSWORD"
      ? `Policy: at least ${policy.data.min_password_length} characters${policy.data.require_uppercase ? ", an uppercase letter" : ""}${policy.data.require_numbers ? ", a number" : ""}${policy.data.require_symbols ? ", a symbol" : ""}.`
      : "API keys and other machine secrets are not checked against the password policy.";

  return (
    <form onSubmit={form.handleSubmit((values) => { setError(null); save.mutate(values); })} noValidate className="space-y-4" autoComplete="off">
      {error && <Alert tone="error">{error}</Alert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Title" error={errors.title?.message}>
          {(props) => <Input {...props} {...form.register("title")} />}
        </Field>
        <Field label="Username / account" error={errors.username?.message}>
          {(props) => <Input {...props} autoComplete="off" {...form.register("username")} />}
        </Field>
        <Field label="Service" error={errors.service?.message}>
          {(props) => (
            <Select {...props} {...form.register("service")}>
              <option value="">No service</option>
              {services.data?.results.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Type" error={errors.secret_type?.message}>
          {(props) => (
            <Select {...props} {...form.register("secret_type")}>
              <option value="PASSWORD">Password</option>
              <option value="API_KEY">API key / token</option>
              <option value="OTHER">Other secret</option>
            </Select>
          )}
        </Field>
        <Field label="Category" error={errors.category?.message}>
          {(props) => <Input {...props} placeholder="e.g. Production" {...form.register("category")} />}
        </Field>
        <Field label="Expiry date" hint="Leave empty to use the policy default for passwords." error={errors.expires_at?.message}>
          {(props) => <Input {...props} type="date" {...form.register("expires_at")} />}
        </Field>
      </div>
      <Field label="Tags" hint="Comma-separated, e.g. prod, database" error={errors.tags?.message}>
        {(props) => <Input {...props} {...form.register("tags")} />}
      </Field>

      <div>
        <Field label={mode === "create" ? "Secret" : "New secret (leave blank to keep the current one)"} hint={policyHint} error={errors.password?.message}>
          {(props) => (
            <div className="flex gap-2">
              <Input {...props} type={showSecret ? "text" : "password"} autoComplete="new-password" spellCheck={false} {...form.register("password")} />
              <Button variant="secondary" onClick={() => setShowSecret((v) => !v)} aria-label={showSecret ? "Hide secret" : "Show secret"}>
                {showSecret ? "Hide" : "Show"}
              </Button>
            </div>
          )}
        </Field>
        <StrengthMeter password={password} />
      </div>

      <PasswordGenerator
        initialLength={policy.data?.min_password_length ?? 20}
        onGenerate={(generated) => {
          form.setValue("password", generated, { shouldValidate: true, shouldDirty: true });
          setShowSecret(true);
        }}
      />

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending}>
          {mode === "create" ? "Save credential" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
