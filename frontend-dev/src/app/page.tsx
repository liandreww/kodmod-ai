"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { HOME_FOR_ROLE, useAuth } from "@/lib/auth-context";

/** Sends each account to its own home, or to sign-in. */
export default function Index() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? HOME_FOR_ROLE[user.role] : "/masuk");
  }, [user, loading, router]);

  return (
    <main className="flex min-h-dvh items-center justify-center p-6">
      <p role="status" className="text-ink-soft">
        Memuat
      </p>
    </main>
  );
}
