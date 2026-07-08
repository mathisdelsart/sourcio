"use client";

import { useId, useState } from "react";
import { login, me, register, type AuthUser, type ConnectionConfig } from "@/lib/api";
import { Button } from "@/components/Button";
import { Card, CardBody } from "@/components/Card";
import { TextField, FieldShell, baseField } from "@/components/TextField";
import { BrandMark } from "@/components/Logo";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface AuthCardProps {
  config: ConnectionConfig;
  /** Called on a successful sign-in with the token and the resolved username. */
  onLogin: (token: string, username: string) => void;
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
 * toggle, username (pseudo) + password, the full-width primary action, and the
 * register→login→me submit flow with toast feedback. Reused by both the locked
 * tool CTA (as a centered modal) and the header account menu, so the two never
 * drift apart.
 */
export function AuthCard({ config, onLogin, onSuccess, onClose, className }: AuthCardProps) {
  const toast = useToast();
  const { t } = useT();
  const passwordId = useId();
  const [mode, setMode] = useState<Mode>("login");
  const [usernameInput, setUsernameInput] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  // Submit failures render INLINE in the card (a page toast would sit behind the
  // modal, invisible). Cleared whenever the user edits a field or switches mode.
  const [error, setError] = useState<string | null>(null);
  // A transient success line shown INLINE too (e.g. "account created, signing you
  // in…"), so the confirmation is visible in the card during the auto sign-in
  // rather than as a page toast that flashes behind the closing modal.
  const [success, setSuccess] = useState<string | null>(null);

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    setError(null);
    setSuccess(null);
    // Start the other form clean: keeping the typed username/password when
    // toggling login <-> register feels wrong (e.g. a login attempt's values
    // bleeding into the register form), so reset the fields on every switch.
    setUsernameInput("");
    setPassword("");
    setShowPassword(false);
  }

  async function submit() {
    if (loading) return;
    // Validate on submit so the primary button can stay solid (a clear, premium
    // call to action) rather than sitting in a washed-out disabled state until
    // both fields are filled; if something is missing, say so inline.
    if (usernameInput.trim().length === 0 || password.length === 0) {
      setError(t("auth.incomplete"));
      return;
    }
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const trimmedUsername = usernameInput.trim();
      if (mode === "register") {
        await register(trimmedUsername, password, config);
        // Confirm INLINE (visible in the card during the auto sign-in that
        // follows) rather than via a page toast hidden behind the modal.
        setSuccess(t("auth.accountCreated"));
      }
      const { access_token } = await login(trimmedUsername, password, config);
      // Confirm the token resolves and read back the canonical identity.
      const user: AuthUser = await me({ ...config, token: access_token });
      onLogin(access_token, user.username);
      toast.push(t("auth.signedInToast", { username: user.username }), "success");
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.failed"));
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
          <div className="relative">
            {/* Soft periwinkle halo: a premium focal point behind the mark. */}
            <div
              aria-hidden
              className="absolute left-1/2 top-1/2 -z-10 h-24 w-24 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand-500/20 blur-2xl"
            />
            <BrandMark className="h-16 w-16 ring-1 ring-black/5" />
          </div>
          <h2 className="mt-5 text-[1.7rem] font-bold tracking-tight text-ink">{t("app.name")}</h2>
          <p className="mt-2 max-w-[17rem] text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">
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
                onClick={() => switchMode(m)}
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
            label={t("auth.username")}
            type="text"
            autoComplete="username"
            placeholder={t("auth.usernamePlaceholder")}
            value={usernameInput}
            onChange={(e) => {
              setUsernameInput(e.target.value);
              setError(null);
            }}
          />

          {/* Password field is inline (not <TextField/>) so it can host a trailing
              show/hide toggle inside the input. */}
          <FieldShell
            label={t("auth.password")}
            hint={mode === "register" ? t("auth.passwordHint") : undefined}
            id={passwordId}
          >
            <div className="relative">
              <input
                id={passwordId}
                type={showPassword ? "text" : "password"}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                placeholder="••••••••"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submit();
                }}
                className={cn(baseField, "pr-11")}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? t("auth.hidePassword") : t("auth.showPassword")}
                aria-pressed={showPassword}
                className={cn(
                  "absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg",
                  "text-zinc-400 transition-colors hover:text-zinc-600 dark:hover:text-zinc-200",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                )}
              >
                {showPassword ? (
                  // Eye with a slash: password is currently visible.
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 3l18 18" />
                    <path d="M10.58 10.58a2 2 0 002.83 2.83" />
                    <path d="M9.36 5.18A9.46 9.46 0 0112 5c5 0 9 4.5 9 7a12.3 12.3 0 01-2.16 3.19M6.61 6.61A12.9 12.9 0 003 12c0 2.5 4 7 9 7a9.3 9.3 0 004.24-1" />
                  </svg>
                ) : (
                  // Open eye: password is currently hidden.
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
          </FieldShell>

          {success && !error && (
            <p
              role="status"
              className="rounded-lg bg-emerald-50 px-3.5 py-2.5 text-sm font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
            >
              {success}
            </p>
          )}

          {error && (
            <p
              role="alert"
              className="rounded-lg bg-red-50 px-3.5 py-2.5 text-sm font-medium text-red-700 dark:bg-red-950/40 dark:text-red-300"
            >
              {error}
            </p>
          )}

          <Button
            className="mt-1 h-11 w-full rounded-xl text-sm"
            onClick={submit}
            loading={loading}
          >
            {mode === "login" ? t("auth.signIn") : t("auth.createAccount")}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
