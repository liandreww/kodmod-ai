"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogOut } from "lucide-react";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

export interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
}

/** The frame shared by the teacher and admin dashboards. */
export function DashboardShell({
  title,
  nav,
  children,
}: {
  title: string;
  nav: NavItem[];
  children: ReactNode;
}) {
  const { user, signOut } = useAuth();
  const pathname = usePathname();

  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#konten" className="skip-link">
        Lompat ke konten
      </a>

      <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3 sm:px-6">
        <span className="font-bold tracking-tight text-ink">KODMOD AI</span>
        <span aria-hidden className="text-line-strong">
          |
        </span>
        <h1 className="mr-auto text-ink-soft">{title}</h1>
        <span className="hidden text-ink-soft sm:inline">{user?.full_name}</span>
        <ThemeToggle />
        <Button variant="ghost" iconOnly onClick={signOut} title="Keluar">
          <LogOut aria-hidden className="h-5 w-5" />
          <span className="sr-only">Keluar</span>
        </Button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <nav aria-label="Navigasi utama" className="border-b border-line bg-surface p-3 lg:w-56 lg:border-b-0 lg:border-r">
          <ul className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
            {nav.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 items-center gap-2 whitespace-nowrap rounded-[10px] px-3 py-2 font-semibold",
                      active ? "bg-brand-wash text-brand-deep" : "text-ink hover:bg-sunken",
                    )}
                  >
                    {item.icon}
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <main id="konten" className="min-w-0 flex-1 p-4 sm:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
