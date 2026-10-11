import type { ReactNode } from "react";

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md">
        <p className="mb-6 text-center text-2xl font-bold tracking-tight">
          Secure<span className="text-brand-600">Vault</span>
        </p>
        <div className="rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <h1 className="text-xl font-semibold">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
          <div className="mt-5">{children}</div>
        </div>
      </div>
    </main>
  );
}
