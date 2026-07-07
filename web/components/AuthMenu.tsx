"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { type ConnectionConfig } from "@/lib/api";
import { AuthCard } from "@/components/AuthCard";
import { Button } from "@/components/Button";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface AuthMenuProps {
  config: ConnectionConfig;
  /** Friendly display name, when the account set one. */
  name: string | null;
  /** Canonical email; shown when no display name is set. */
  email: string | null;
  onLogin: (token: string, email: string, displayName?: string | null) => void;
  onLogout: () => void;
}

/**
 * Header account menu. When signed out, the trigger opens the shared
 * {@link AuthCard} as a centered modal overlay (not a cramped dropdown); when
 * signed in, it shows the account's display name (falling back to the email) and
 * a logout action. The JWT is lifted to the parent (persisted to localStorage)
 * and sent on requests as a bearer token, additively to the optional API key.
 */
export function AuthMenu({ config, name, email, onLogin, onLogout }: AuthMenuProps) {
  const toast = useToast();
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const isAuthed = Boolean(email);
  const label = name || email;
  // First letter of the display name (or email) for the avatar badge.
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

      {/* Signed-in: a compact dropdown with the identity and a logout action. */}
      {open && isAuthed && (
        <div
          role="dialog"
          aria-label={t("auth.aria")}
          className="animate-fade-in absolute right-0 z-30 mt-2 w-72 rounded-xl border border-zinc-200 bg-white p-4 shadow-card-hover dark:border-zinc-700 dark:bg-zinc-900"
        >
          <div className="space-y-3">
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              {t("auth.signedInAs")}{" "}
              <span className="font-medium text-zinc-900 dark:text-zinc-100">{label}</span>
            </p>
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
