import type { Metadata } from "next";
import "bootstrap/dist/css/bootstrap.min.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "./globals.css";
import { ActivityProvider } from "@/components/activity";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "KODMOD Test Console",
  description: "Manual test console for KODMOD AI. Not for production use.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ActivityProvider>
          <Shell>{children}</Shell>
        </ActivityProvider>
      </body>
    </html>
  );
}
