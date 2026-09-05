"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui";
import { createPreference } from "@/lib/preference";

type Theme = "light" | "dark";

const isTheme = (value: string): value is Theme => value === "light" || value === "dark";

/**
 * The stored theme. The inline script in the document head applies it before
 * first paint; this preference keeps React in step with what that script did.
 */
const themePreference = createPreference<Theme>("kodmod.theme", "light", isTheme);

export function ThemeToggle() {
  const theme = themePreference.use();
  const dark = theme === "dark";

  // Keep the attribute the stylesheet reads in sync with the stored choice.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return (
    <Button
      variant="ghost"
      iconOnly
      onClick={() => themePreference.set(dark ? "light" : "dark")}
      aria-pressed={dark}
      title={dark ? "Mode terang" : "Mode gelap"}
    >
      {dark ? <Sun aria-hidden className="h-5 w-5" /> : <Moon aria-hidden className="h-5 w-5" />}
      <span className="sr-only">{dark ? "Ganti ke mode terang" : "Ganti ke mode gelap"}</span>
    </Button>
  );
}
