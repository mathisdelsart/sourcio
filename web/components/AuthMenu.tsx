"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { type ConnectionConfig } from "@/lib/api";
import { AuthCard } from "@/components/AuthCard";
import { Button } from "@/components/Button";
import { baseField } from "@/components/TextField";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface AuthMenuProps {
  config: ConnectionConfig;
  /** The signed-in account's username (pseudonym); null when signed out. */
  username: string | null;
  onLogin: (token: string, username: string) => void;
  onLogout: () => void;
  /** The visitor's own OpenAI key (shared with the Documents upload card). */
  openaiKey: string;
  /** Persist a new OpenAI key (writes localStorage in the parent). */
  onOpenaiKeyChange: (value: string) => void;
}

/**
 * Header account menu. When signed out, the trigger opens the shared
 * {@link AuthCard} as a centered modal overlay (not a cramped dropdown); when
 * signed in, it shows the account's username and a logout action. The JWT is
 * lifted to the parent (persisted to localStorage) and sent on requests as a
 * bearer token, additively to the optional API key.
 */
export function AuthMenu({
  config,
  username,
  onLogin,
  onLogout,
  openaiKey,
  onOpenaiKeyChange,
}: AuthMenuProps) {
  const toast = useToast();
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const openaiKeyId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const isAuthed = Boolean(username);
  const label = username;
  // First letter of the username for the avatar badge.
  const initial = (label ?? "").trim().charAt(0).toUpperCase() || "?";

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  // While open, close on Escape or an outside click, returning focus to the
  // trigger so keyboard users are never stranded inside a dismissed dialog. The
  // outside-click guard only applies to the signed-in dropdown; the signed-out
  // modal handles its own backdrop click below.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    function onClick(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    if (isAuthed) document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open, isAuthed]);

  function logout() {
    onLogout();
    setOpen(false);
    toast.push(t("auth.signedOutToast"), "info");
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={cn(
          "inline-flex items-center gap-2 text-sm font-semibold transition-colors",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
          isAuthed
            ? "rounded-full border border-zinc-200 bg-white py-1 pl-1 pr-3 text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
            : "rounded-lg bg-brand-600 px-4 py-2 text-white shadow-sm shadow-brand-600/20 hover:bg-brand-500 active:bg-brand-700",
        )}
      >
        {isAuthed ? (
          <>
            {/* Initial-avatar badge on a brand-tinted circle. */}
            <span
              className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white dark:bg-brand-500"
              aria-hidden
            >
              {initial}
            </span>
            <span className="max-w-[10rem] truncate">{label}</span>
            <svg
              aria-hidden
              viewBox="0 0 24 24"
              className={cn(
                "h-4 w-4 shrink-0 text-zinc-400 transition-transform dark:text-zinc-500",
                open && "rotate-180",
              )}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </>
        ) : (
          <span>{t("header.signIn")}</span>
        )}
      </button>

      {/* Signed-in: a compact dropdown with the identity, the personal OpenAI-key
          setting, and a logout action. */}
      {open && isAuthed && (
        <div
          role="dialog"
          aria-label={t("auth.aria")}
          className="animate-fade-in absolute right-0 z-30 mt-2 w-80 rounded-xl border border-zinc-200 bg-white p-4 shadow-card-hover dark:border-zinc-700 dark:bg-zinc-900"
        >
          <div className="space-y-4">
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              {t("auth.signedInAs")}{" "}
              <span className="font-medium text-zinc-900 dark:text-zinc-100">{label}</span>
            </p>

            {/* Personal OpenAI key — a global, discoverable setting. When set, it
                is sent with every request so all LLM calls use the visitor's own
                premium model instead of the free one. Masked with a show/hide
                toggle; persisted to the browser only (same storage as upload). */}
            <div className="space-y-1.5 border-t border-zinc-100 pt-3 dark:border-zinc-800">
              <label
                htmlFor={openaiKeyId}
                className="block text-sm font-medium text-zinc-700 dark:text-zinc-300"
              >
                {t("settings.openaiKey.label")}
              </label>
              <div className="relative">
                <input
                  id={openaiKeyId}
                  // A plain text input masked with CSS (not type="password"), plus
                  // anti-autofill hints, so the browser never offers to "save this
                  // password" — this is an API key, not a credential.
                  type="text"
                  name="sourcio-openai-key"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-1p-ignore
                  data-lpignore="true"
                  placeholder="sk-…"
                  value={openaiKey}
                  onChange={(e) => onOpenaiKeyChange(e.target.value)}
                  className={cn(baseField, "pr-11", !showKey && "[-webkit-text-security:disc]")}
                />
                <button
                  type="button"
                  onClick={() => setShowKey((v) => !v)}
                  aria-label={showKey ? t("settings.openaiKey.hide") : t("settings.openaiKey.show")}
                  aria-pressed={showKey}
                  className={cn(
                    "absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg",
                    "text-zinc-400 transition-colors hover:text-zinc-600 dark:hover:text-zinc-200",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                  )}
                >
                  {showKey ? (
                    <svg
                      aria-hidden
                      viewBox="0 0 24 24"
                      className="h-4 w-4"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                      <path d="M1 1l22 22" />
                    </svg>
                  ) : (
                    <svg
                      aria-hidden
                      viewBox="0 0 24 24"
                      className="h-4 w-4"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
              <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
                {t("settings.openaiKey.note")}
              </p>
            </div>

            <Button variant="secondary" className="w-full" onClick={logout}>
              {t("auth.signOut")}
            </Button>
          </div>
        </div>
      )}

      {/* Signed-out: a centered modal overlay hosting the shared AuthCard.
          Rendered through a portal on document.body so a transformed ancestor
          (the sticky header) can't capture the fixed overlay and shift it. */}
      {open &&
        !isAuthed &&
        createPortal(
          <div
            className="animate-fade-in fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4 backdrop-blur-sm"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) close();
            }}
          >
            <div role="dialog" aria-modal="true" aria-label={t("auth.aria")}>
              <AuthCard
                config={config}
                onLogin={onLogin}
                onSuccess={() => setOpen(false)}
                onClose={close}
              />
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
