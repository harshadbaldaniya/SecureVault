import { useQuery } from "@tanstack/react-query";
import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { Alert, Button, PageLoader, LinkButton } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { useDeviceRegistration } from "@/features/devices/deviceRegistration";
import { NotificationBell } from "@/features/notifications/NotificationsPage";
import { ToastStack } from "@/features/notifications/Toasts";
import { useRealtime } from "@/features/notifications/realtime";
import { api } from "@/services/api";
import type { Permission, SecurityPolicy } from "@/types/api";

interface NavItem {
  to: string;
  label: string;
  permission?: Permission;
}

const NAV: NavItem[] = [
  { to: "/", label: "Home" },
  { to: "/vault", label: "Credentials" },
  { to: "/vault/notes", label: "Secure notes" },
  { to: "/sharing", label: "Sharing" },
  { to: "/access-requests", label: "Access requests" },
  { to: "/devices", label: "Devices" },
  { to: "/employees", label: "Employees", permission: "users.view" },
  { to: "/departments", label: "Departments" },
  { to: "/services", label: "Service catalog" },
  { to: "/policy", label: "Security policy" },
  { to: "/alerts", label: "Security alerts", permission: "alerts.manage" },
  { to: "/lockdown", label: "Emergency lockdown", permission: "lockdown.manage" },
  { to: "/reports", label: "Reports", permission: "reports.view" },
  { to: "/audit", label: "Audit log", permission: "audit.view" },
  { to: "/security", label: "Account security" },
];

const ROLE_LABEL = { ORG_ADMIN: "Organization Administrator", SEC_ADMIN: "Security Administrator", EMPLOYEE: "Employee" } as const;

/** Shown instead of the app when a lockdown covers a user who may not be signed in. */
function LockdownScreen({ onSignOut }: { onSignOut: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div role="alert" className="max-w-md rounded-lg bg-white p-8 text-center shadow ring-1 ring-red-200">
        <p className="text-4xl" aria-hidden="true">
          ⛔
        </p>
        <h1 className="mt-4 text-xl font-semibold">Emergency lockdown in effect</h1>
        <p className="mt-2 text-sm text-slate-600">The security team has frozen access to secrets. You will be able to continue once they lift the lockdown.</p>
        <Button className="mt-6" variant="secondary" onClick={onSignOut}>
          Sign out
        </Button>
      </div>
    </main>
  );
}

export function AppLayout() {
  const { user, logout, can } = useAuth();
  const [open, setOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  const signedIn = Boolean(user);
  const device = useDeviceRegistration(signedIn);
  const policy = useQuery({ queryKey: ["policy"], queryFn: () => api.get<SecurityPolicy>("/policy/"), enabled: signedIn });
  const { toasts, dismissToast } = useRealtime(signedIn);
  const navRef = useRef<HTMLElement>(null);
  const [navMore, setNavMore] = useState(false);

  // Scrollbars are hidden, so a fade at the bottom edge is the only hint that more navigation items are below.
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const update = () => setNavMore(nav.scrollHeight - nav.scrollTop - nav.clientHeight > 4);
    update();
    nav.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      nav.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  });

  // The page content scrolls inside <main>, not the window, so a new page must start at the top explicitly.
  useEffect(() => {
    if (mainRef.current) mainRef.current.scrollTop = 0;
  }, [pathname]);

  if (!user) return null;

  const isLockdownManager = can("lockdown.manage");
  if (user.lockdown && !isLockdownManager) return <LockdownScreen onSignOut={() => void logout()} />;

  const links = NAV.filter((item) => !item.permission || can(item.permission));
  const untrustedDevice = policy.data?.require_device_trust && device.data && device.data.trust_state !== "TRUSTED";

  // App shell: exactly one viewport tall, so the window never scrolls. The sidebar navigation and <main> are the only
  // scroll containers (min-h-0 / min-w-0 let flex children shrink instead of stretching the shell). The shell and <main>
  // are also `relative`: absolutely positioned content (e.g. Tailwind's sr-only table captions) would otherwise take the
  // page as its containing block, escape the overflow clipping and stretch the document.
  return (
    <div className="relative flex h-dvh flex-col overflow-hidden lg:flex-row">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>

      <header className="flex shrink-0 items-center justify-between bg-slate-900 px-4 py-3 text-white lg:hidden">
        <span className="font-bold">
          Secure<span className="text-blue-400">Vault</span>
        </span>
        <button type="button" className="rounded px-3 py-1.5 text-sm ring-1 ring-white/30" aria-expanded={open} aria-controls="sidebar" onClick={() => setOpen((v) => !v)}>
          Menu
        </button>
      </header>

      <aside id="sidebar" className={`${open ? "flex" : "hidden"} no-scrollbar max-h-[70dvh] shrink-0 flex-col overflow-y-auto overscroll-contain bg-slate-900 text-slate-200 lg:flex lg:max-h-none lg:min-h-0 lg:w-64 lg:overflow-visible`}>
        <div className="hidden shrink-0 px-6 py-5 text-xl font-bold text-white lg:block">
          Secure<span className="text-blue-400">Vault</span>
        </div>
        <div className="relative flex min-h-0 flex-1 flex-col">
          <nav ref={navRef} aria-label="Main" className="no-scrollbar min-h-0 flex-1 space-y-1 overflow-y-auto overflow-x-hidden overscroll-contain px-3 py-2">
            {links.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/" || item.to === "/vault"}
                onClick={() => setOpen(false)}
                className={({ isActive }) => `block rounded-md px-3 py-2 text-sm ${isActive ? "bg-white/10 font-medium text-white" : "hover:bg-white/5"}`}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          {navMore && <div aria-hidden="true" data-testid="nav-more" className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-slate-900 to-transparent" />}
        </div>
        <div className="shrink-0 border-t border-white/10 px-3 py-2">
          <NotificationBell />
        </div>
        <div className="shrink-0 border-t border-white/10 p-4 text-sm">
          <p className="truncate font-medium text-white">{user.full_name}</p>
          <p className="truncate text-xs text-slate-400">{ROLE_LABEL[user.role]}</p>
          <p className="truncate text-xs text-slate-400">{user.organization.name}</p>
          <Button variant="secondary" className="mt-3 w-full" onClick={() => void logout()}>
            Sign out
          </Button>
        </div>
      </aside>

      <main ref={mainRef} id="main" className="no-scrollbar relative min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain p-4 max-sm:pb-[calc(1rem+var(--toast-space,0px))] sm:p-6 lg:p-8">
        <div className="mx-auto max-w-6xl space-y-4">
          {user.lockdown && (
            <Alert
              tone="error"
              action={
                <LinkButton to="/lockdown" size="sm">
                  Manage lockdown
                </LinkButton>
              }
            >
              <strong>Emergency lockdown active</strong> ({user.lockdown.scope === "GLOBAL" ? "organization-wide" : "one account"}). Secrets cannot be revealed, copied, edited or shared by anyone until it is lifted.
            </Alert>
          )}
          {untrustedDevice && (
            <Alert
              tone="warning"
              action={
                <LinkButton to="/devices" size="sm">
                  View devices
                </LinkButton>
              }
            >
              This device is <strong>{device.data?.trust_state.toLowerCase()}</strong>. Your organization requires a trusted device for sensitive actions, so revealing or changing secrets is blocked here until a security administrator approves it.
            </Alert>
          )}
          <Suspense fallback={<PageLoader />}>
            <Outlet />
          </Suspense>
        </div>
      </main>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
