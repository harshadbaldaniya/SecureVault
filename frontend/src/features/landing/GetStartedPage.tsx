import { Link } from "react-router-dom";

import { ShieldIcon, UsersIcon } from "@/components/icons";

import { btnSecondary, Footer, Header } from "./PublicChrome";

/**
 * Public "how do I get access" page. SecureVault has no self-registration: an organization administrator invites each
 * person, and the first administrator is created on the server. So this page explains that rather than offering a form.
 */

const STEPS = [
  { title: "Ask your administrator for access", text: "Contact the person who runs SecureVault for your organization. They add you by email address and choose your role." },
  { title: "Open your invitation", text: "You will receive a one-time invitation link. It can be used once and it expires, so use it soon after it arrives." },
  { title: "Set your password and sign in", text: "Choose a strong password to activate your account, sign in, and turn on two-step verification if your organization asks for it." },
];

export function GetStartedPage() {
  return (
    <div className="flex min-h-dvh flex-col bg-slate-950 text-slate-100 antialiased">
      <a href="#get-started-main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-slate-900">
        Skip to content
      </a>
      <Header home="/" onGetStarted />
      <main id="get-started-main" className="relative isolate flex-1 overflow-hidden">
        <div aria-hidden="true" className="absolute inset-0 -z-10 bg-[radial-gradient(50rem_26rem_at_75%_-10%,rgba(37,99,235,0.32),transparent),radial-gradient(34rem_22rem_at_0%_40%,rgba(14,165,233,0.12),transparent)]" />
        <div className="mx-auto max-w-3xl px-4 pb-20 pt-14 sm:px-6 lg:pt-20">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-sky-400/30 bg-sky-400/10 px-3 py-1 text-xs font-medium text-sky-200">
            <ShieldIcon className="size-3.5" /> Access is by invitation
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-white sm:text-5xl">Get started with SecureVault</h1>
          <p className="mt-5 text-base leading-7 text-slate-300 sm:text-lg">
            SecureVault accounts are created through invitations from your organization&apos;s administrator. There is no public sign-up, which keeps your organization&apos;s credentials limited to the people it has chosen.
          </p>

          <ol className="mt-10 space-y-4">
            {STEPS.map((step, index) => (
              <li key={step.title} className="flex gap-4 rounded-xl border border-white/10 bg-slate-900/70 p-5">
                <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-600 text-sm font-bold text-white">
                  {index + 1}
                </span>
                <div>
                  <h2 className="text-base font-semibold text-white">
                    <span className="sr-only">Step {index + 1}: </span>
                    {step.title}
                  </h2>
                  <p className="mt-1 text-sm leading-6 text-slate-300">{step.text}</p>
                </div>
              </li>
            ))}
          </ol>

          <section aria-labelledby="need-access" className="mt-8 rounded-xl border border-sky-400/20 bg-gradient-to-br from-blue-700/30 via-slate-900 to-slate-900 p-6">
            <div className="flex items-start gap-4">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-blue-600/20 text-sky-300 ring-1 ring-sky-400/20">
                <UsersIcon className="size-5" />
              </span>
              <div>
                <h2 id="need-access" className="text-lg font-semibold text-white">
                  Need access? Contact your administrator
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-300">
                  Ask your organization&apos;s SecureVault administrator to invite you, and tell them the email address you want to use. Never share your password or your invitation link with anyone.
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-400">Setting up SecureVault for a new organization? The first administrator account is created by whoever deploys it, from the server.</p>
              </div>
            </div>
          </section>

          <div className="mt-10">
            <Link to="/" className={btnSecondary}>
              Back to home
            </Link>
          </div>
        </div>
      </main>
      <Footer home="/" />
    </div>
  );
}
