import { forwardRef } from "react";
import { cn } from "@/lib/cn";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

const variants: Record<Variant, string> = {
  primary:
    "bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800 disabled:bg-indigo-300 " +
    "dark:bg-indigo-500 dark:hover:bg-indigo-400 dark:active:bg-indigo-600 dark:disabled:bg-indigo-500/40 dark:disabled:text-white/60",
  secondary:
    "bg-white text-zinc-800 border border-zinc-200 hover:bg-zinc-50 active:bg-zinc-100 disabled:text-zinc-400 " +
    "dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-700 dark:active:bg-zinc-600 dark:disabled:text-zinc-500",
  ghost:
    "bg-transparent text-zinc-600 hover:bg-zinc-100 active:bg-zinc-200 disabled:text-zinc-300 " +
    "dark:text-zinc-300 dark:hover:bg-zinc-800 dark:active:bg-zinc-700 dark:disabled:text-zinc-600",
};

/** Primary action button with loading and disabled states. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", loading = false, disabled, className, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium",
        "transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-zinc-950",
        "disabled:cursor-not-allowed",
        variants[variant],
        className,
      )}
      {...props}
    >
      {loading && <Spinner className={variant === "primary" ? "border-white/40 border-t-white" : ""} />}
      {children}
    </button>
  );
});
