import { cn } from "@/lib/cn";

/** A surface card: white, hairline border, soft shadow. */
export function Card({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-zinc-200 bg-white shadow-card dark:border-zinc-800 dark:bg-zinc-900",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-zinc-100 px-6 py-4 dark:border-zinc-800">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">{title}</h2>
        {description && (
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-300">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}

export function CardBody({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cn("px-6 py-6", className)}>{children}</div>;
}
