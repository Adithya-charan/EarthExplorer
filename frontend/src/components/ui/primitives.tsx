import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Card({
  children,
  className,
  as: Tag = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    // min-w-0 lets a card shrink inside a grid; otherwise a wide table forces the whole page to scroll sideways.
    <Tag className={cx("min-w-0 rounded-lg border border-line bg-surface shadow-card", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function CardHeader({
  title,
  subtitle,
  actions,
  id,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
      <div className="min-w-0">
        <h2 id={id} className="text-[15px] font-semibold text-ink">
          {title}
        </h2>
        {subtitle ? <p className="mt-0.5 text-sm text-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("px-4 py-4 sm:px-5", className)}>{children}</div>;
}

type Tone = "neutral" | "accent" | "info" | "warn" | "danger";
const TONES: Record<Tone, string> = {
  neutral: "bg-surface-muted text-ink-soft border-line-strong",
  accent: "bg-accent-soft text-accent-strong border-[#a8d8d2]",
  info: "bg-info-soft text-[#00507c] border-[#a9cfe4]",
  warn: "bg-warn-soft text-warn border-warn-line",
  danger: "bg-danger-soft text-danger border-danger-line",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
  icon,
  role,
}: {
  tone?: Exclude<Tone, "neutral" | "accent"> | "accent";
  title?: ReactNode;
  children?: ReactNode;
  icon?: ReactNode;
  role?: "alert" | "status" | "note";
}) {
  const styles: Record<string, string> = {
    info: "bg-info-soft border-[#a9cfe4] text-[#00415f]",
    accent: "bg-accent-soft border-[#a8d8d2] text-accent-strong",
    warn: "bg-warn-soft border-warn-line text-warn",
    danger: "bg-danger-soft border-danger-line text-danger",
  };
  return (
    <div role={role} className={cx("flex gap-3 rounded-lg border px-4 py-3 text-sm", styles[tone])}>
      {icon ? <span aria-hidden="true" className="mt-0.5 shrink-0">{icon}</span> : null}
      <div className="min-w-0">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={title ? "mt-0.5" : undefined}>{children}</div> : null}
      </div>
    </div>
  );
}

export function MetricCard({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3 shadow-card">
      <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase tracking-wide text-muted">
        <span>{label}</span>
        {icon ? <span aria-hidden="true">{icon}</span> : null}
      </div>
      <div className="tabular mt-1 text-2xl font-semibold text-ink">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-muted">{hint}</div> : null}
    </div>
  );
}

export function PageHeading({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-ink sm:text-[26px]">{title}</h1>
        {description ? <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Button({
  children,
  variant = "secondary",
  className,
  ...rest
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost";
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles = {
    primary: "bg-accent text-white hover:bg-accent-strong border-accent disabled:bg-[#8fb9b5] disabled:border-[#8fb9b5]",
    secondary: "bg-surface text-ink hover:bg-surface-muted border-line-strong disabled:text-muted",
    ghost: "bg-transparent text-ink-soft hover:bg-surface-muted border-transparent disabled:text-muted",
  };
  return (
    <button
      type="button"
      className={cx(
        "inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed",
        styles[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
