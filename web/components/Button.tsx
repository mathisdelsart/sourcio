import { forwardRef } from "react";
import { cn } from "@/lib/cn";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const sizes: Record<Size, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-3.5 py-2 text-sm",
};

const variants: Record<Variant, string> = {
  primary:
    "bg-brand-600 text-white shadow-sm shadow-brand-600/20 hover:bg-brand-500 active:bg-brand-700 disabled:opacity-50",
  secondary:
    "bg-white text-zinc-800 border border-zinc-200 hover:bg-zinc-50 active:bg-zinc-100 disabled:text-zinc-400 " +
    "dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-700 dark:active:bg-zinc-600 dark:disabled:text-zinc-500",
  ghost:
    "bg-transparent text-zinc-600 hover:bg-zinc-100 active:bg-zinc-200 disabled:text-zinc-300 " +
    "dark:text-zinc-300 dark:hover:bg-zinc-800 dark:active:bg-zinc-700 dark:disabled:text-zinc-600",
};

/** Primary action button with loading and disabled states. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, disabled, className, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium",
        sizes[size],
        "transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-zinc-950",
        "disabled:cursor-not-allowed",
        variants[variant],
        className,
      )}
      {...props}
    >
      {loading && <Spinner className={variant === "primary" ? "border-current/40 border-t-current" : ""} />}
      {children}
    </button>
  );
});
