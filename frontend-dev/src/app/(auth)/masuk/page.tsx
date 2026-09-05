"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { HOME_FOR_ROLE, useAuth } from "@/lib/auth-context";

const schema = z.object({
  username: z.string().min(1, "Isi nama pengguna."),
  password: z.string().min(1, "Isi kata sandi."),
});

type Values = z.infer<typeof schema>;

export default function SignIn() {
  const { user, loading, signIn } = useAuth();
  const router = useRouter();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (!loading && user) router.replace(HOME_FOR_ROLE[user.role]);
  }, [user, loading, router]);

  async function onSubmit(values: Values) {
    try {
      const account = await signIn(values.username, values.password);
      router.replace(HOME_FOR_ROLE[account.role]);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Tidak dapat terhubung ke server.";
      setError("root", { message });
    }
  }

  return (
    <>
      <h1 className="text-3xl font-bold tracking-tight text-ink">Masuk</h1>

      <form onSubmit={handleSubmit(onSubmit)} className="mt-8 flex flex-col gap-5" noValidate>
        <Field label="Nama pengguna" error={errors.username?.message}>
          {({ id, describedBy }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={!!errors.username}
              autoComplete="username"
              autoCapitalize="none"
              autoFocus
              {...register("username")}
            />
          )}
        </Field>

        <Field label="Kata sandi" error={errors.password?.message}>
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="password"
              aria-describedby={describedBy}
              aria-invalid={!!errors.password}
              autoComplete="current-password"
              {...register("password")}
            />
          )}
        </Field>

        {errors.root ? (
          <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 font-semibold text-danger">
            {errors.root.message}
          </p>
        ) : null}

        <Button type="submit" loading={isSubmitting} className="mt-1">
          Masuk
        </Button>
      </form>

      <p className="mt-8 text-ink-soft">
        Belum punya akun?{" "}
        <Link href="/daftar" className="font-semibold text-brand-deep underline underline-offset-4">
          Daftar dengan kode undangan
        </Link>
      </p>
    </>
  );
}
