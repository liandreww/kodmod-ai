"use client";

import { BookOpen, Users } from "lucide-react";

import { DashboardShell } from "@/components/dashboard-shell";
import { Guard } from "@/components/guard";

const NAV = [
  { href: "/guru", label: "Siswa", icon: <Users aria-hidden className="h-5 w-5" /> },
  {
    href: "/guru/mata-pelajaran",
    label: "Mata pelajaran",
    icon: <BookOpen aria-hidden className="h-5 w-5" />,
  },
];

export default function GuruLayout({ children }: { children: React.ReactNode }) {
  return (
    <Guard role="teacher">
      <DashboardShell title="Guru" nav={NAV}>
        {children}
      </DashboardShell>
    </Guard>
  );
}
