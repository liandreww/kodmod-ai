"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { HOME_FOR_ROLE, useAuth } from "@/lib/auth-context";
import type { Role } from "@/lib/types";

/**
 * Client-side role gate.
 *
 * The API enforces roles on every request, so this is about not showing someone
 * a page they cannot use, rather than about security.
 */
export function Guard({ role, children }: { role: Role; children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/masuk");
    else if (user.role !== role) router.replace(HOME_FOR_ROLE[user.role]);
  }, [user, loading, role, router]);

  if (loading || !user || user.role !== role) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-6">
        <p role="status" className="text-ink-soft">
          Memuat
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
