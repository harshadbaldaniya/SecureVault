import { Link } from "react-router-dom";

import { ShieldIcon } from "./icons";

/**
 * The SecureVault mark and wordmark: one component for every screen (public pages, sign-in, the signed-in sidebar and
 * header), so the branding cannot drift. "dark" is for dark surfaces (navy pages, the sidebar); "light" is for white or
 * pale surfaces (sign-in and notice screens). It links to "/", which is the landing page when signed out and Home when
 * signed in.
 */
export function BrandLogo({ tone = "dark", size = "md", className = "" }: { tone?: "dark" | "light"; size?: "md" | "lg"; className?: string }) {
  const light = tone === "light";
  return (
    <Link
      to="/"
      aria-label="SecureVault home"
      className={`inline-flex items-center gap-2 rounded-md font-bold tracking-tight ${size === "lg" ? "text-xl" : "text-lg"} ${light ? "text-slate-900" : "text-white"} focus-visible:outline-2 focus-visible:outline-offset-2 ${light ? "focus-visible:outline-brand-600" : "focus-visible:outline-sky-300"} ${className}`}
    >
      <ShieldIcon className={size === "lg" ? "size-7" : "size-6"} style={{ color: light ? "var(--color-brand-600)" : undefined }} />
      <span>
        Secure<span className={light ? "text-brand-600" : "text-sky-400"}>Vault</span>
      </span>
    </Link>
  );
}
