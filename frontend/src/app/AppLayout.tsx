import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";

import { Alert, Button } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { useDeviceRegistration } from "@/features/devices/deviceRegistration";
import { NotificationBell } from "@/features/notifications/NotificationsPage";
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
  { to: "/audit", label: "Audit log", permission: "audit.view" },
  { to: "/security", label: "Account security" },
];

const ROLE_LABEL = { ORG_ADMIN: "Organization Administrator", SEC_ADMIN: "Security Administrator", EMPLOYEE: "Employee" } as const;
const PRIORITY_TONE = { LOW: "info", NORMAL: "info", HIGH: "warning", CRITICAL: "error" } as const;

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
  const signedIn = Boolean(user);
  const device = useDeviceRegistration(signedIn);
  const policy = useQuery({ queryKey: ["policy"], queryFn: () => api.get<SecurityPolicy>("/policy/"), enabled: signedIn });
  const { toast, dismissToast } = useRealtime(signedIn);
  if (!user) return null;

  const isLockdownManager = can("lockdown.manage");
  if (user.lockdown && !isLockdownManager) return <LockdownScreen onSignOut={() => void logout()} />;

  const links = NAV.filter((item) => !item.permission || can(item.permission));
  const untrustedDevice = policy.data?.require_device_trust && device.data && device.data.trust_state !== "TRUSTED";

  return (
    <div className="min-h-screen lg:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>

      <header className="flex items-center justify-between bg-slate-900 px-4 py-3 text-white lg:hidden">
        <span className="font-bold">
          Secure<span className="text-blue-400">Vault</span>
        </span>
        <button type="button" className="rounded px-3 py-1.5 text-sm ring-1 ring-white/30" aria-expanded={open} aria-controls="sidebar" onClick={() => setOpen((v) => !v)}>
          Menu
        </button>
      </header>

      <aside id="sidebar" className={`${open ? "block" : "hidden"} bg-slate-900 text-slate-200 lg:flex lg:min-h-screen lg:w-64 lg:shrink-0 lg:flex-col`}>
        <div className="hidden px-6 py-5 text-xl font-bold text-white lg:block">
          Secure<span className="text-blue-400">Vault</span>
        </div>
        <nav aria-label="Main" className="flex-1 space-y-1 px-3 py-2">
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
        <div className="px-3 pb-2">
          <NotificationBell />
        </div>
        <div className="border-t border-white/10 p-4 text-sm">
          <p className="truncate font-medium text-white">{user.full_name}</p>
          <p className="truncate text-xs text-slate-400">{ROLE_LABEL[user.role]}</p>
          <p className="truncate text-xs text-slate-400">{user.organization.name}</p>
          <Button variant="secondary" className="mt-3 w-full" onClick={() => void logout()}>
            Sign out
          </Button>
        </div>
      </aside>

      <main id="main" className="min-w-0 flex-1 p-4 sm:p-6 lg:p-8">
        <div className="mx-auto max-w-6xl space-y-4">
          {user.lockdown && (
            <Alert tone="error">
              <strong>Emergency lockdown active</strong> ({user.lockdown.scope === "GLOBAL" ? "organization-wide" : "one account"}). Secrets cannot be revealed, copied, edited or shared by anyone until it is lifted.{" "}
              <Link to="/lockdown" className="font-medium underline">
                Manage lockdown
              </Link>
            </Alert>
          )}
          {untrustedDevice && (
            <Alert tone="warning">
              This device is <strong>{device.data?.trust_state.toLowerCase()}</strong>. Your organization requires a trusted device for sensitive actions, so revealing or changing secrets is blocked here until a security administrator approves it.{" "}
              <Link to="/devices" className="font-medium underline">
                View devices
              </Link>
            </Alert>
          )}
          <Outlet />
        </div>
      </main>

      {toast && (
        <div className="fixed bottom-4 right-4 z-40 w-80 max-w-[calc(100%-2rem)]" role="status" aria-live="polite">
          <Alert tone={PRIORITY_TONE[toast.priority]}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{toast.title}</p>
                {toast.message && <p className="mt-1 text-xs">{toast.message}</p>}
                {toast.link && (
                  <Link to={toast.link} className="mt-1 inline-block text-xs underline" onClick={dismissToast}>
                    Open
                  </Link>
                )}
              </div>
              <button type="button" className="text-xs underline" onClick={dismissToast}>
                Dismiss
              </button>
            </div>
          </Alert>
        </div>
      )}
    </div>
  );
}
