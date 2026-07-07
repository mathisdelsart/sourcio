"use client";

import { useState } from "react";
import { login, me, register, type AuthUser, type ConnectionConfig } from "@/lib/api";
import { Button } from "@/components/Button";
import { Card, CardBody } from "@/components/Card";
import { TextField } from "@/components/TextField";
import { BrandMark } from "@/components/Logo";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface AuthCardProps {
  config: ConnectionConfig;
  /** Called on a successful sign-in with the token and the resolved identity. */
  onLogin: (token: string, email: string, displayName?: string | null) => void;
  /** Optional hook fired after a successful sign-in (e.g. to close a modal). */
  onSuccess?: () => void;
  /** When set, a close (✕) button is shown (used in the modal, not the gate). */
  onClose?: () => void;
  className?: string;
}

type Mode = "login" | "register";

/**
 * Shared, self-contained sign-in / register card built on the design system.
 *
 * A single source of truth for the auth form: the segmented login/register
 * toggle, email + password (+ an optional display name on register), the
 * full-width primary action, and the register→login→me submit flow with toast
 * feedback. Reused by both the full-screen {@link AuthGate} and the header
 * account menu (as a centered modal), so the two never drift apart.
 */
export function AuthCard({ config, onLogin, onSuccess, onClose, className }: AuthCardProps) {
  const toast = useToast();
  const { t } = useT();
  const [mode, setMode] = useState<Mode>("login");
  const [emailInput, setEmailInput] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);

  const canSubmit = emailInput.trim().length > 0 && password.length > 0 && !loading;

  async function submit() {
    if (!canSubmit) return;
    setLoading(true);
    try {
      const trimmedEmail = emailInput.trim();
      if (mode === "register") {
        await register(trimmedEmail, password, config, displayName);
        toast.push(t("auth.accountCreated"), "success");
      }
      const { access_token } = await login(trimmedEmail, password, config);
      // Confirm the token resolves and read back the canonical identity.
      const user: AuthUser = await me({ ...config, token: access_token });
      onLogin(access_token, user.email, user.display_name ?? null);
      toast.push(
        t("auth.signedInToast", { email: user.display_name || user.email }),
        "success",
      );
      onSuccess?.();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("auth.failed"), "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className={cn("relative w-full max-w-sm animate-fade-in", className)}>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label={t("auth.close")}
          className={cn(
            "absolute right-3.5 top-3.5 inline-flex h-8 w-8 items-center justify-center rounded-full",
            "text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
          )}
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>
      )}
      <CardBody className="p-7 sm:p-9">
        <div className="flex flex-col items-center text-center">
          <BrandMark className="h-14 w-14" />
          <span className="mt-4 text-2xl font-bold tracking-tight text-ink">{t("app.name")}</span>
          <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
            {t("auth.cardSubtitle")}
          </p>
        </div>

        <div className="mt-6 space-y-4">
          {/* Segmented pill toggle: a white active segment on a soft track
              (Linear/Notion style) rather than a hard-edged bordered row. */}
          <div className="flex rounded-xl bg-zinc-100 p-1 text-sm dark:bg-zinc-800">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                className={cn(
                  "flex-1 rounded-lg px-3 py-2 font-medium transition-all",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                  mode === m
                    ? "bg-white text-brand-700 shadow-sm dark:bg-zinc-950 dark:text-brand-300"
                    : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200",
                )}
              >
                {m === "login" ? t("auth.signIn") : t("auth.register")}
              </button>
            ))}
          </div>

          <TextField
            label={t("auth.email")}
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={emailInput}
            onChange={(e) => setEmailInput(e.target.value)}
          />

          {mode === "register" && (
            <TextField
              label={t("auth.displayName")}
              type="text"
              autoComplete="nickname"
              placeholder={t("auth.displayNamePlaceholder")}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          )}

          <TextField
            label={t("auth.password")}
            type="password"
            autoComplete={mode === "register" ? "new-password" : "current-password"}
            placeholder="••••••••"
            hint={mode === "register" ? t("auth.passwordHint") : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
          />

          <Button
            className="mt-1 h-11 w-full rounded-xl text-sm"
            onClick={submit}
            loading={loading}
            disabled={!canSubmit}
          >
            {mode === "login" ? t("auth.signIn") : t("auth.createAccount")}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
