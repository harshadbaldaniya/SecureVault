import { useState } from "react";
import { Link } from "react-router-dom";

import { BrandLogo } from "@/components/BrandLogo";
import { MenuIcon } from "@/components/icons";

/** Header, footer and button styles shared by the public pages (landing, get started) so they look like one site. */

export const NAV = [
  { href: "#features", label: "Features" },
  { href: "#security", label: "Security" },
  { href: "#how-it-works", label: "How It Works" },
];

export const ring = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300";
export const btnPrimary = `inline-flex min-h-11 items-center justify-center rounded-md bg-brand-600 px-5 text-sm font-semibold text-white shadow-lg shadow-blue-900/40 transition-colors hover:bg-blue-500 ${ring}`;
export const btnSecondary = `inline-flex min-h-11 items-center justify-center rounded-md px-5 text-sm font-semibold text-white ring-1 ring-inset ring-white/30 transition-colors hover:bg-white/10 ${ring}`;

/** `home` is the path in-page links resolve against: "" on the landing page itself, "/" from any other public page. */
export function Header({ home = "", onGetStarted = false }: { home?: string; /** True on the get-started page itself: its own button is dropped and Sign In becomes the one action. */ onGetStarted?: boolean }) {
  const [open, setOpen] = useState(false);
  const link = `rounded-md px-3 py-2 text-sm text-slate-300 transition-colors hover:text-white ${ring}`;
  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-slate-950/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <BrandLogo />
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {NAV.map((item) => (
            <a key={item.href} href={home + item.href} className={link}>
              {item.label}
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-2 md:flex">
          <Link to="/login" className={`${onGetStarted ? btnPrimary : btnSecondary} min-h-10`}>
            Sign In
          </Link>
          {!onGetStarted && (
            <Link to="/get-started" className={`${btnPrimary} min-h-10`}>
              Get Started
            </Link>
          )}
        </div>
        <button
          type="button"
          className={`inline-flex size-10 items-center justify-center rounded-md text-white ring-1 ring-inset ring-white/30 md:hidden ${ring}`}
          aria-expanded={open}
          aria-controls="landing-menu"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((v) => !v)}
        >
          <MenuIcon className="size-5" />
        </button>
      </div>
      {open && (
        <nav id="landing-menu" aria-label="Main mobile" className="border-t border-white/10 px-4 pb-4 pt-2 md:hidden">
          <ul className="space-y-1">
            {NAV.map((item) => (
              <li key={item.href}>
                <a href={home + item.href} className={`${link} block`} onClick={() => setOpen(false)}>
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex gap-2">
            <Link to="/login" className={`${onGetStarted ? btnPrimary : btnSecondary} flex-1`}>
              Sign In
            </Link>
            {!onGetStarted && (
              <Link to="/get-started" className={`${btnPrimary} flex-1`}>
                Get Started
              </Link>
            )}
          </div>
        </nav>
      )}
    </header>
  );
}

export function Footer({ home = "" }: { home?: string }) {
  const link = `rounded-sm text-sm text-slate-400 hover:text-white ${ring}`;
  return (
    <footer className="border-t border-white/10 bg-slate-950">
      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-10 sm:px-6 md:flex-row md:items-start md:justify-between">
        <div className="max-w-xs">
          <BrandLogo />
          <p className="mt-3 text-sm text-slate-400">Credential and access management for organizations.</p>
        </div>
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-12 gap-y-2">
          <a href={`${home}#features`} className={link}>
            Features
          </a>
          <Link to="/login" className={link}>
            Sign In
          </Link>
          <a href={`${home}#security`} className={link}>
            Security
          </a>
          <Link to="/forgot-password" className={link}>
            Forgot password
          </Link>
          <a href={`${home}#how-it-works`} className={link}>
            How It Works
          </a>
        </nav>
      </div>
      <p className="border-t border-white/5 px-4 py-4 text-center text-xs text-slate-400">&copy; {new Date().getFullYear()} SecureVault</p>
    </footer>
  );
}

