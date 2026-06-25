"use client";

import { useState } from "react";
import { login, me, register, type AuthUser, type ConnectionConfig } from "@/lib/api";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/cn";

interface AuthMenuProps {
  config: ConnectionConfig;
  email: string | null;
  onLogin: (token: string, email: string) => void;
  onLogout: () => void;
}

type Mode = "login" | "register";

/**
 * Header account menu. When signed out, it opens a small login/register form;
 * when signed in, it shows the user's email and a logout action. The JWT is
 * lifted to the parent (persisted to localStorage) and sent on requests as a
 * bearer token, additively to the optional API key.
 */
export function AuthMenu({ config, email, onLogin, onLogout }: AuthMenuProps) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("login");
  const [emailInput, setEmailInput] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const isAuthed = Boolean(email);
  const canSubmit = emailInput.trim().length > 0 && password.length > 0 && !loading;

  function reset() {
    setEmailInput("");
    setPassword("");
  }

  async function submit() {
    if (!canSubmit) return;
    setLoading(true);
    try {
      const trimmedEmail = emailInput.trim();
      if (mode === "register") {
        await register(trimmedEmail, password, config);
        toast.push("Account created. Signing you in…", "success");
      }
      const { access_token } = await login(trimmedEmail, password, config);
      // Confirm the token resolves and read back the canonical email.
      const user: AuthUser = await me({ ...config, token: access_token });
      onLogin(access_token, user.email);
      toast.push(`Signed in as ${user.email}.`, "success");
      reset();
      setOpen(false);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "Authentication failed.", "error");
    } finally {
      setLoading(false);
    }
  }

  function logout() {
    onLogout();
    setOpen(false);
    toast.push("Signed out.", "info");
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={cn(
          "inline-flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-1.5",
          "text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50",
          "dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-zinc-950",
        )}
      >
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            isAuthed ? "bg-emerald-500" : "bg-zinc-300 dark:bg-zinc-600",
          )}
          aria-hidden
        />
        {isAuthed ? (
          <span className="max-w-[12rem] truncate">{email}</span>
        ) : (
          <span>Sign in</span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Account"
          className="animate-fade-in absolute right-0 z-30 mt-2 w-72 rounded-xl border border-zinc-200 bg-white p-4 shadow-card-hover dark:border-zinc-700 dark:bg-zinc-900"
        >
          {isAuthed ? (
            <div className="space-y-3">
              <p className="text-sm text-zinc-600 dark:text-zinc-300">
                Signed in as{" "}
                <span className="font-medium text-zinc-900 dark:text-zinc-100">{email}</span>
              </p>
              <Button variant="secondary" className="w-full" onClick={logout}>
                Sign out
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex rounded-lg border border-zinc-200 p-0.5 text-sm dark:border-zinc-700">
                {(["login", "register"] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    className={cn(
                      "flex-1 rounded-md px-2 py-1 font-medium transition-colors",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500",
                      mode === m
                        ? "bg-indigo-600 text-white dark:bg-indigo-500"
                        : "text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800",
                    )}
                  >
                    {m === "login" ? "Sign in" : "Register"}
                  </button>
                ))}
              </div>
              <TextField
                label="Email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
              />
              <TextField
                label="Password"
                type="password"
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                placeholder="••••••••"
                hint={mode === "register" ? "At least 8 characters." : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submit();
                }}
              />
              <Button className="w-full" onClick={submit} loading={loading} disabled={!canSubmit}>
                {mode === "login" ? "Sign in" : "Create account"}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
