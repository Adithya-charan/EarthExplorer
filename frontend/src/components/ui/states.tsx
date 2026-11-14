import { AlertCircle, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import type { ApiError } from "@/lib/api";
import { Button, cx } from "./primitives";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("skeleton", className)} />;
}

/** Skeleton placeholder shown while data loads. Announced politely to assistive tech. */
export function LoadingState({
  label = "Loading",
  variant = "block",
}: {
  label?: string;
  variant?: "chart" | "cards" | "table" | "block";
}) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" data-testid="loading-state">
      <span className="sr-only">{label}…</span>
      {variant === "cards" ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : variant === "chart" ? (
        <Skeleton className="h-[360px] w-full" />
      ) : variant === "table" ? (
        <div className="space-y-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          <Skeleton className="h-5 w-1/3" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div
      data-testid="empty-state"
      className="flex flex-col items-center rounded-lg border border-dashed border-line-strong bg-surface-muted px-6 py-10 text-center"
    >
      <span aria-hidden="true" className="mb-3 text-muted">
        {icon ?? <Inbox size={28} />}
      </span>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description ? <div className="mt-1 max-w-xl text-sm text-muted">{description}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  title = "Something went wrong",
  onRetry,
}: {
  error: Pick<ApiError, "message" | "code"> | { message: string; code?: string };
  title?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      data-testid="error-state"
      className="flex flex-col gap-3 rounded-lg border border-danger-line bg-danger-soft px-5 py-4 text-sm text-danger sm:flex-row sm:items-start"
    >
      <AlertCircle aria-hidden="true" size={20} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{title}</p>
        <p className="mt-0.5 break-words">{error.message}</p>
        {error.code ? <p className="mt-1 text-xs opacity-80">Error code: {error.code}</p> : null}
      </div>
      {onRetry ? (
        <Button onClick={onRetry} className="shrink-0">
          <RefreshCw aria-hidden="true" size={14} /> Try again
        </Button>
      ) : null}
    </div>
  );
}
