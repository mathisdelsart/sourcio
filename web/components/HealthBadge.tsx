"use client";

import { useEffect, useRef, useState } from "react";
import { checkHealth, type ConnectionConfig } from "@/lib/api";
import { cn } from "@/lib/cn";

type Status = "checking" | "online" | "offline";

/** Persistent badge that polls `/health` and shows a green/red status dot. */
export function HealthBadge({ config }: { config: ConnectionConfig }) {
  const [status, setStatus] = useState<Status>("checking");
  const configRef = useRef(config);
  configRef.current = config;

  useEffect(() => {
    let active = true;
    const ping = async () => {
      const ok = await checkHealth(configRef.current);
      if (active) setStatus(ok ? "online" : "offline");
    };
    ping();
    const timer = setInterval(ping, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
    // Re-run when the connection target changes.
  }, [config.baseUrl, config.apiKey]);

  const label =
    status === "online" ? "Backend online" : status === "offline" ? "Backend offline" : "Checking…";
  const dot =
    status === "online"
      ? "bg-emerald-500"
      : status === "offline"
        ? "bg-red-500"
        : "bg-zinc-300";

  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-600"
      title={label}
    >
      <span className="relative flex h-2 w-2">
        {status === "online" && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        )}
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", dot)} />
      </span>
      {label}
    </span>
  );
}
