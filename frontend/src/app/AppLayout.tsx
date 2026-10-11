import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { Button } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { NotificationBell } from "@/features/notifications/NotificationsPage";
import type { Permission } from "@/types/api";

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
  { to: "/employees", label: "Employees", permission: "users.view" },
  { to: "/departments", label: "Departments" },
  { to: "/services", label: "Service catalog" },
  { to: "/policy", label: "Security policy" },
  { to: "/audit", label: "Audit log", permission: "audit.view" },
  { to: "/security", label: "Account security" },
];

const ROLE_LABEL = { ORG_ADMIN: "Organization Administrator", SEC_ADMIN: "Security Administrator", EMPLOYEE: "Employee" } as const;

export function AppLayout() {
  const { user, logout, can } = useAuth();
  const [open, setOpen] = useState(false);
  if (!user) return null;

  const links = NAV.filter((item) => !item.permission || can(item.permission));

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
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
