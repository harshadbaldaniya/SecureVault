import { useEffect, type ComponentType, type SVGProps } from "react";
import { Link, useLocation } from "react-router-dom";

import { ApprovalIcon, DeviceIcon, KeyIcon, NoteIcon, ShareIcon, ShieldIcon, UsersIcon } from "@/components/icons";

import { btnPrimary, btnSecondary, Footer, Header } from "./PublicChrome";

type IconType = ComponentType<SVGProps<SVGSVGElement>>;

/**
 * Public marketing page, shown at "/" to visitors who are not signed in. It makes only claims that are true of this
 * application: encryption is server-side (not end-to-end or zero-knowledge), and no certification or audit is implied.
 * Accounts are created by invitation, so "Get Started" opens an information page (/get-started) rather than a registration
 * form, and "Sign In" opens the existing sign-in screen.
 */

const FEATURES: { icon: IconType; title: string; text: string }[] = [
  { icon: KeyIcon, title: "Secure Credential Management", text: "Store passwords and API keys encrypted with AES-256-GCM. Lists show metadata only; a secret appears only when you ask to reveal it, and every reveal is recorded." },
  { icon: NoteIcon, title: "Secure Notes", text: "Keep licence tokens and configuration snippets in encrypted notes, archived and restored without ever being searchable by content." },
  { icon: ShareIcon, title: "Controlled Sharing", text: "Share a credential with a colleague at view or edit level, with an expiry, a view-once option and a delegation tree showing who passed access on." },
  { icon: ApprovalIcon, title: "Access Requests and Approvals", text: "People ask for access with a reason and a duration. Owners approve or decline, and approved access ends by itself." },
  { icon: UsersIcon, title: "Employee and Organization Management", text: "Invite people by email or bulk-import from Excel, organise them in departments, and assign Administrator, Security Administrator or Employee roles." },
  { icon: DeviceIcon, title: "Device and Security Monitoring", text: "Approve, suspend or revoke devices, review security alerts, and use emergency lockdown to freeze access to secrets across the organization." },
];

const PILLARS: { title: string; text: string; points: string[] }[] = [
  {
    title: "Encryption",
    text: "Secrets are encrypted with AES-256-GCM before they are stored, using a data key per organization that is itself wrapped by a master key held outside the database.",
    points: ["Encrypted at rest in the database", "Secrets never appear in lists, logs or exports", "Encryption happens on the server: it is not end-to-end or zero-knowledge"],
  },
  {
    title: "Access control",
    text: "What someone can see and do depends on their role and on what has been shared with them, and the server checks it on every request.",
    points: ["Role-based permissions, scoped to your organization", "Optional two-step verification with an authenticator app", "Secure session cookies and CSRF protection"],
  },
  {
    title: "Monitoring",
    text: "Security-relevant actions are written to an append-only audit log in which each entry is chained to the one before it, so tampering is detectable.",
    points: ["Audit log with an integrity check", "Device trust and unusual-sign-in alerts", "Reports for compliance, hygiene and incidents"],
  },
];

const STEPS = [
  { title: "Sign in securely", text: "Use your organization account, with two-step verification when it is turned on. Your administrator invites you; there is no public sign-up." },
  { title: "Organize and protect credentials", text: "Add credentials and notes, group them by service, and let SecureVault flag weak, reused or expiring secrets." },
  { title: "Manage sharing and monitor access", text: "Share with expiry, review access requests, and follow every reveal, share and sign-in in the audit log." },
];

/** A CSS-only picture of the product: a vault list with masked secrets. Decorative, so hidden from assistive technology. */
function VaultPreview() {
  const rows = [
    { name: "Production database", meta: "Database · rotated 12 days ago", tone: "bg-emerald-400/15 text-emerald-300", label: "Strong" },
    { name: "Payments API key", meta: "API key · expires in 9 days", tone: "bg-amber-400/15 text-amber-300", label: "Expiring" },
    { name: "Staging SSH access", meta: "Shared with 3 people", tone: "bg-sky-400/15 text-sky-300", label: "Shared" },
  ];
  return (
    <div aria-hidden="true" className="relative mx-auto w-full max-w-lg motion-safe:animate-[landing-float_8s_ease-in-out_infinite]">
      <div className="absolute -inset-6 rounded-[2rem] bg-gradient-to-tr from-blue-600/30 via-sky-400/10 to-transparent blur-2xl" />
      <div className="relative overflow-hidden rounded-xl border border-white/10 bg-slate-900/90 shadow-2xl shadow-blue-950/60 ring-1 ring-white/5">
        <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
          <span className="size-2.5 rounded-full bg-red-400/70" />
          <span className="size-2.5 rounded-full bg-amber-300/70" />
          <span className="size-2.5 rounded-full bg-emerald-400/70" />
          <span className="ml-3 text-xs text-slate-400">Credentials</span>
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-emerald-400/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
            <ShieldIcon className="size-3" /> Encrypted
          </span>
        </div>
        <ul className="divide-y divide-white/5">
          {rows.map((row) => (
            <li key={row.name} className="flex items-center gap-3 px-4 py-3.5">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/5 text-sky-300">
                <KeyIcon className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-100">{row.name}</p>
                <p className="truncate text-xs text-slate-400">{row.meta}</p>
              </div>
              <span className="hidden font-mono text-xs tracking-widest text-slate-400 sm:inline">••••••••••</span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${row.tone}`}>{row.label}</span>
            </li>
          ))}
        </ul>
        <div className="grid grid-cols-3 gap-px border-t border-white/10 bg-white/5 text-center">
          {[
            ["24", "credentials"],
            ["3", "pending requests"],
            ["0", "open alerts"],
          ].map(([value, label]) => (
            <div key={label} className="bg-slate-900 px-2 py-3">
              <p className="text-lg font-semibold text-white">{value}</p>
              <p className="text-[11px] text-slate-400">{label}</p>
            </div>
          ))}
        </div>
      </div>
      <p className="mt-3 text-center text-[11px] text-slate-400">Illustration with sample data</p>
    </div>
  );
}

function Hero() {
  return (
    <section className="relative isolate overflow-hidden">
      <div aria-hidden="true" className="absolute inset-0 -z-10 bg-[radial-gradient(60rem_30rem_at_70%_-10%,rgba(37,99,235,0.35),transparent),radial-gradient(40rem_25rem_at_0%_30%,rgba(14,165,233,0.14),transparent)]" />
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-20 pt-14 sm:px-6 lg:grid-cols-2 lg:gap-8 lg:pb-28 lg:pt-24">
        <div>
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-sky-400/30 bg-sky-400/10 px-3 py-1 text-xs font-medium text-sky-200">
            <ShieldIcon className="size-3.5" /> Credential and access management for teams
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-white sm:text-5xl lg:text-[3.4rem] lg:leading-[1.08]">
            Your Credentials. <span className="text-sky-400">Protected.</span> Organized. Under Control.
          </h1>
          <p className="mt-5 max-w-xl text-base leading-7 text-slate-300 sm:text-lg">
            SecureVault helps organizations securely manage credentials, protect sensitive notes, control sharing, and monitor access from one centralized platform.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/get-started" className={btnPrimary}>
              Get Started
            </Link>
            <Link to="/login" className={btnSecondary}>
              Sign In
            </Link>
          </div>
          <p className="mt-4 text-sm text-slate-400">Accounts are created by your organization administrator through an invitation.</p>
        </div>
        <VaultPreview />
      </div>
    </section>
  );
}

function TrustStrip() {
  const items = ["AES-256-GCM encryption", "Role-based access", "Two-step verification", "Tamper-evident audit log"];
  return (
    <section aria-label="Security highlights" className="border-y border-white/10 bg-slate-900/50">
      <ul className="mx-auto grid max-w-6xl grid-cols-2 gap-4 px-4 py-6 text-center text-sm font-medium text-slate-200 sm:px-6 md:grid-cols-4">
        {items.map((item) => (
          <li key={item} className="flex items-center justify-center gap-2">
            <ShieldIcon className="size-4 shrink-0 text-sky-400" />
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SectionTitle({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="text-sm font-semibold uppercase tracking-widest text-sky-400">{eyebrow}</p>
      <h2 className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">{title}</h2>
      <p className="mt-4 text-base leading-7 text-slate-300">{text}</p>
    </div>
  );
}

function Features() {
  return (
    <section id="features" className="scroll-mt-20 px-4 py-20 sm:px-6 lg:py-24">
      <SectionTitle eyebrow="Features" title="Everything your team needs to handle secrets well" text="One place to store, share and review access to the credentials your organization depends on." />
      <ul className="mx-auto mt-12 grid max-w-6xl gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, text }) => (
          <li key={title} className="group rounded-xl border border-white/10 bg-gradient-to-b from-white/[0.06] to-white/[0.02] p-6 transition-colors hover:border-sky-400/40">
            <span className="flex size-11 items-center justify-center rounded-lg bg-blue-600/20 text-sky-300 ring-1 ring-sky-400/20">
              <Icon className="size-5" />
            </span>
            <h3 className="mt-5 text-lg font-semibold text-white">{title}</h3>
            <p className="mt-2 text-sm leading-6 text-slate-300">{text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-20 border-y border-white/10 bg-slate-900/40 px-4 py-20 sm:px-6 lg:py-24">
      <SectionTitle eyebrow="How It Works" title="From sign-in to full visibility in three steps" text="A simple workflow that keeps people productive and leaves a clear record." />
      <ol className="mx-auto mt-12 grid max-w-6xl gap-5 md:grid-cols-3">
        {STEPS.map((step, index) => (
          <li key={step.title} className="relative rounded-xl border border-white/10 bg-slate-900/70 p-6">
            <span className="flex size-10 items-center justify-center rounded-full bg-brand-600 text-sm font-bold text-white" aria-hidden="true">
              {index + 1}
            </span>
            <h3 className="mt-5 text-lg font-semibold text-white">
              <span className="sr-only">Step {index + 1}: </span>
              {step.title}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-300">{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Security() {
  return (
    <section id="security" className="scroll-mt-20 px-4 py-20 sm:px-6 lg:py-24">
      <SectionTitle
        eyebrow="Security"
        title="Built to be inspected, not just trusted"
        text="Clear controls, explained plainly. SecureVault has not been through an independent security audit or certification, and we do not claim otherwise."
      />
      <div className="mx-auto mt-12 grid max-w-6xl gap-5 lg:grid-cols-3">
        {PILLARS.map((pillar) => (
          <article key={pillar.title} className="rounded-xl border border-white/10 bg-gradient-to-b from-blue-600/10 to-transparent p-6">
            <h3 className="text-lg font-semibold text-white">{pillar.title}</h3>
            <p className="mt-2 text-sm leading-6 text-slate-300">{pillar.text}</p>
            <ul className="mt-4 space-y-2 text-sm text-slate-200">
              {pillar.points.map((point) => (
                <li key={point} className="flex gap-2">
                  <ShieldIcon className="mt-0.5 size-4 text-sky-400" />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="px-4 pb-20 sm:px-6 lg:pb-24" aria-labelledby="final-cta">
      <div className="mx-auto max-w-4xl rounded-2xl border border-sky-400/20 bg-gradient-to-br from-blue-700/40 via-slate-900 to-slate-900 p-8 text-center sm:p-12">
        <h2 id="final-cta" className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Bring your team&apos;s credentials under control
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-base leading-7 text-slate-300">Already have an account? Sign in. New to SecureVault? Find out how access works: your organization&apos;s administrator invites you.</p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link to="/get-started" className={btnPrimary}>
            Get Started
          </Link>
          <Link to="/login" className={btnSecondary}>
            Sign In
          </Link>
        </div>
      </div>
    </section>
  );
}

export function LandingPage() {
  const { hash } = useLocation();
  // Arriving from another public page with "/#security": the section does not exist until this page has rendered, so the
  // browser's own jump to the fragment finds nothing. Scroll there once it is on screen.
  useEffect(() => {
    if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
  }, [hash]);

  return (
    <div className="min-h-dvh bg-slate-950 text-slate-100 antialiased">
      <a href="#landing-main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-slate-900">
        Skip to content
      </a>
      <Header />
      <main id="landing-main">
        <Hero />
        <TrustStrip />
        <Features />
        <HowItWorks />
        <Security />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}
