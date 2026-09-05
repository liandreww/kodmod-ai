import { Guard } from "@/components/guard";

export const metadata = { title: "Ruang Belajar" };

export default function BelajarLayout({ children }: { children: React.ReactNode }) {
  return <Guard role="student">{children}</Guard>;
}
