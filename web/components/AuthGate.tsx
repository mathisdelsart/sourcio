"use client";

import { type ConnectionConfig } from "@/lib/api";
import { AuthCard } from "@/components/AuthCard";
import { BrandMark } from "@/components/Logo";
import { LanguageToggle } from "@/components/LanguageToggle";
import { useT } from "@/lib/i18n";

interface AuthGateProps {
  config: ConnectionConfig;
  onLogin: (token: string, username: string) => void;
}

/**
 * Full-screen blocking sign-in gate shown when the backend enforces
 * authentication (`require_auth`) and the visitor has no token yet. It stands in
 * for the whole app until the user is signed in, wrapping the shared
 * {@link AuthCard} — the single source of truth for the register/login/me flow —
 * centered on the page.
 */
export function AuthGate({ config, onLogin }: AuthGateProps) {
  const { t } = useT();

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 dark:bg-zinc-950">
      <header className="flex items-center justify-between px-4 py-4 sm:px-6 sm:py-5">
        <div className="flex items-center gap-3">
          <BrandMark className="h-10 w-10" />
          <div className="leading-tight">
            <p className="text-sm font-semibold text-ink">{t("app.name")}</p>
            <p className="text-xs text-zinc-500">{t("app.tagline")}</p>
          </div>
        </div>
        <LanguageToggle />
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <AuthCard config={config} onLogin={onLogin} />
      </main>
    </div>
  );
}
