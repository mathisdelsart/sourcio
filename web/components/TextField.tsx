import { forwardRef, useId } from "react";
import { cn } from "@/lib/cn";

export const baseField =
  "w-full rounded-lg border border-zinc-300 bg-white px-3.5 py-2.5 text-sm text-zinc-900 placeholder:text-zinc-400 " +
  "transition-colors focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 " +
  "disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-400 " +
  "dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500 " +
  "dark:focus:border-brand-400 dark:focus:ring-brand-400/20 dark:disabled:bg-zinc-800/50 dark:disabled:text-zinc-500";

interface FieldShellProps {
  label?: string;
  hint?: string;
  id: string;
  children: React.ReactNode;
}

export function FieldShell({ label, hint, id, children }: FieldShellProps) {
  return (
    <div className="space-y-1.5">
      {label && (
        <label
          htmlFor={id}
          className="block text-sm font-medium text-zinc-700 dark:text-zinc-300"
        >
          {label}
        </label>
      )}
      {children}
      {hint && <p className="text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>}
    </div>
  );
}

interface TextFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
}

/** A labelled single-line text input. */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(
  function TextField({ label, hint, className, id, ...props }, ref) {
    const autoId = useId();
    const fieldId = id ?? autoId;
    return (
      <FieldShell label={label} hint={hint} id={fieldId}>
        <input ref={ref} id={fieldId} className={cn(baseField, className)} {...props} />
      </FieldShell>
    );
  },
);

interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  hint?: string;
}

/** A labelled multi-line text input. */
export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(
  function TextArea({ label, hint, className, id, ...props }, ref) {
    const autoId = useId();
    const fieldId = id ?? autoId;
    return (
      <FieldShell label={label} hint={hint} id={fieldId}>
        <textarea
          ref={ref}
          id={fieldId}
          className={cn(baseField, "resize-y leading-relaxed", className)}
          {...props}
        />
      </FieldShell>
    );
  },
);
