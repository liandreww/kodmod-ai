"use client";

import { KeyRound, Users } from "lucide-react";

import { DashboardShell } from "@/components/dashboard-shell";
import { Guard } from "@/components/guard";

const NAV = [
  { href: "/admin", label: "Akun", icon: <Users aria-hidden className="h-5 w-5" /> },
  {
    href: "/admin/undangan",
    label: "Kode undangan",
    icon: <KeyRound aria-hidden className="h-5 w-5" />,
  },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <Guard role="admin">
      <DashboardShell title="Admin" nav={NAV}>
        {children}
      </DashboardShell>
    </Guard>
  );
}
