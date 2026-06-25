"use client";

import { useEffect, useState } from "react";
import { KEYS, writeLocal } from "@/lib/storage";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

type Theme = "light" | "dark";

/** Sun icon, shown in dark mode to indicate "switch to light". */
function SunIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-[18px] w-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

/** Moon icon, shown in light mode to indicate "switch to dark". */
function MoonIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-[18px] w-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
}

/**
 * Header light/dark toggle. The initial class on <html> is set by the inline
 * script in the root layout (no flash); this control mirrors that state, then
 * persists changes to localStorage and updates the class on click.
 */
export function ThemeToggle() {
  const { t } = useT();
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  // Mirror whatever the pre-paint script already applied to <html>.
  useEffect(() => {
    const isDark = document.documentElement.classList.contains("dark");
    setTheme(isDark ? "dark" : "light");
    setMounted(true);
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
    writeLocal(KEYS.theme, next);
  }

  const isDark = theme === "dark";
  const label = isDark ? t("theme.switchToLight") : t("theme.switchToDark");

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      aria-pressed={isDark}
      className={cn(
        "inline-flex h-9 w-9 items-center justify-center rounded-lg border text-zinc-600",
        "border-zinc-200 bg-white transition-colors hover:bg-zinc-50",
        "dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2",
        "dark:focus-visible:ring-offset-zinc-950",
      )}
    >
      {/* Render the icon only after mount so SSR/CSR markup matches. */}
      {mounted ? (isDark ? <SunIcon /> : <MoonIcon />) : <span className="h-[18px] w-[18px]" />}
    </button>
  );
}
