import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6 text-center">
      <h1 className="text-2xl font-bold tracking-tight text-ink">Halaman tidak ditemukan</h1>
      <Link href="/" className="font-semibold text-brand-deep underline underline-offset-4">
        Kembali ke beranda
      </Link>
    </main>
  );
}
