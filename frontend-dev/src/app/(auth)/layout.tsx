import { ThemeToggle } from "@/components/theme-toggle";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh">
      <header className="flex items-center justify-between px-6 py-4">
        <span className="font-bold tracking-tight text-ink">KODMOD AI</span>
        <ThemeToggle />
      </header>
      <main className="mx-auto flex w-full max-w-[26rem] flex-col px-6 pb-16 pt-6">
        {children}
      </main>
    </div>
  );
}
