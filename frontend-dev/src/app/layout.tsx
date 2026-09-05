import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible, JetBrains_Mono } from "next/font/google";

import { Providers } from "@/app/providers";
import "./globals.css";

/**
 * Atkinson Hyperlegible was drawn by the Braille Institute specifically so that
 * characters which normally collide (I/l/1, O/0, rn/m) stay distinguishable to
 * readers with low vision. For this product that is not a stylistic preference,
 * it is the requirement. JetBrains Mono carries invitation codes and ids, where
 * a misread character costs someone their account.
 */
const sans = Atkinson_Hyperlegible({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-atkinson",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "KODMOD AI",
  description: "Tutor belajar berbasis suara untuk siswa tunanetra.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Never block zoom: magnification is a primary accommodation here.
  maximumScale: 5,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" suppressHydrationWarning>
      <head>
        {/* Applied before paint so the page never flashes the wrong theme. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('kodmod.theme');if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.dataset.theme='dark'}else{document.documentElement.dataset.theme='light'}}catch(e){}`,
          }}
        />
      </head>
      <body className={`${sans.variable} ${mono.variable}`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
