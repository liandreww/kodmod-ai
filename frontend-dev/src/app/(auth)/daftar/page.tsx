"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button, Field, Input, Select } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { HOME_FOR_ROLE, useAuth } from "@/lib/auth-context";

const schema = z.object({
  full_name: z.string().min(1, "Isi nama lengkap."),
  username: z
    .string()
    .min(3, "Minimal 3 karakter.")
    .regex(/^[a-zA-Z0-9._-]+$/, "Hanya huruf, angka, titik, garis bawah, dan strip."),
  password: z.string().min(8, "Minimal 8 karakter."),
  role: z.enum(["student", "teacher"]),
  invitation_code: z.string().min(1, "Isi kode undangan."),
});

type Values = z.infer<typeof schema>;

export default function Register() {
  const { register: createAccount } = useAuth();
  const router = useRouter();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { role: "student" },
  });

  async function onSubmit(values: Values) {
    try {
      const account = await createAccount(values);
      router.replace(HOME_FOR_ROLE[account.role]);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Tidak dapat terhubung ke server.";
      setError("root", { message });
    }
  }

  return (
    <>
      <h1 className="text-3xl font-bold tracking-tight text-ink">Daftar</h1>

      <form onSubmit={handleSubmit(onSubmit)} className="mt-8 flex flex-col gap-5" noValidate>
        <Field label="Nama lengkap" error={errors.full_name?.message}>
          {({ id, describedBy }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={!!errors.full_name}
              autoComplete="name"
              autoFocus
              {...register("full_name")}
            />
          )}
        </Field>

        <Field label="Nama pengguna" error={errors.username?.message}>
          {({ id, describedBy }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={!!errors.username}
              autoComplete="username"
              autoCapitalize="none"
              {...register("username")}
            />
          )}
        </Field>

        <Field label="Kata sandi" hint="Minimal 8 karakter." error={errors.password?.message}>
          {({ id, describedBy }) => (
            <Input
              id={id}
              type="password"
              aria-describedby={describedBy}
              aria-invalid={!!errors.password}
              autoComplete="new-password"
              {...register("password")}
            />
          )}
        </Field>

        <Field label="Saya mendaftar sebagai" error={errors.role?.message}>
          {({ id, describedBy }) => (
            <Select id={id} aria-describedby={describedBy} {...register("role")}>
              <option value="student">Siswa</option>
              <option value="teacher">Guru</option>
            </Select>
          )}
        </Field>

        <Field label="Kode undangan" error={errors.invitation_code?.message}>
          {({ id, describedBy }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={!!errors.invitation_code}
              autoCapitalize="characters"
              spellCheck={false}
              className="font-mono tracking-widest uppercase"
              {...register("invitation_code")}
            />
          )}
        </Field>

        {errors.root ? (
          <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 font-semibold text-danger">
            {errors.root.message}
          </p>
        ) : null}

        <Button type="submit" loading={isSubmitting} className="mt-1">
          Buat akun
        </Button>
      </form>

      <p className="mt-8 text-ink-soft">
        Sudah punya akun?{" "}
        <Link href="/masuk" className="font-semibold text-brand-deep underline underline-offset-4">
          Masuk
        </Link>
      </p>
    </>
  );
}
