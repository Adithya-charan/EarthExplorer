"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AlertTriangle, BarChart3, Database, Globe2, History, Loader2, Mountain, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Earth Time Machine", icon: History },
  { href: "/analytics", label: "Change Analytics", icon: BarChart3 },
  { href: "/deep-time", label: "Deep-Time Analytics", icon: Mountain },
  { href: "/data", label: "Data & Methods", icon: Database },
];

/** Colours used by every chart so a dataset, a model or a change keeps one colour across the app. */
export const C = {
  ink: "#e8f1ff",
  soft: "#b6c6e3",
  muted: "#8da2c4",
  grid: "rgba(148,180,255,0.13)",
  accent: "#38bdf8",
  loss: "#ff4d5e",
  gain: "#35e08a",
  warn: "#fbbf24",
  earthbyte: "#fbbf24",
  paleomap: "#38bdf8",
  violet: "#a78bfa",
  orange: "#fb923c",
  series: ["#38bdf8", "#35e08a", "#fbbf24", "#a78bfa", "#fb923c", "#f472b6", "#22d3ee", "#94a3b8"],
};

export const tooltipStyle = {
  contentStyle: { background: "rgba(7,15,34,0.96)", border: "1px solid rgba(148,180,255,0.25)", borderRadius: 10, color: C.ink, fontSize: 12 },
  labelStyle: { color: C.soft },
  itemStyle: { color: C.ink },
};
export const axisProps = { stroke: C.muted, tick: { fill: C.muted, fontSize: 11 }, tickLine: false } as const;

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  if (path === "/") return <>{children}</>;
  return (
    <div className="nxp" data-testid="nasax-shell">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-sky-500 focus:px-3 focus:py-2 focus:text-white">
        Skip to main content
      </a>
      <header className="sticky top-0 z-30 border-b border-[color:var(--nx-line)] bg-[rgba(3,8,22,0.85)] backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5" aria-label="NASAX Earth Time Machine home">
            <Globe2 className="h-6 w-6 text-[color:var(--nx-accent)]" aria-hidden />
            <span className="leading-tight">
              <span className="block text-[16px] font-bold tracking-wide">NASAX</span>
              <span className="block text-[10px] uppercase tracking-[0.18em] text-[color:var(--nx-muted)]">Earth Time Machine</span>
            </span>
          </Link>
          <nav aria-label="Main" className="flex flex-1 flex-wrap items-center gap-1">
            {NAV.map((n) => {
              const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
              const Icon = n.icon;
              return (
                <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${active ? "bg-white/12 text-white" : "text-[color:var(--nx-soft)] hover:bg-white/8"}`}>
                  <Icon className="h-4 w-4" aria-hidden /> {n.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:py-8">
        {children}
      </main>
      <footer className="border-t border-[color:var(--nx-line)] px-4 py-4 text-xs text-[color:var(--nx-muted)] sm:px-6">
        <p className="mx-auto max-w-[1400px]">NASAX · Satellite Observations, Illustrative Datasets and Geological Reconstructions are kept apart and always labelled. Results describe the selected data only and do not establish causes.</p>
      </footer>
    </div>
  );
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
      {children ? <p className="mt-1 max-w-3xl text-[14px] leading-relaxed text-[color:var(--nx-soft)]">{children}</p> : null}
    </div>
  );
}

export function Card({ title, subtitle, children, className = "", right, testid }: { title?: string; subtitle?: string; children: ReactNode; className?: string; right?: ReactNode; testid?: string }) {
  return (
    <section className={`nx-glass p-4 sm:p-5 ${className}`} data-testid={testid}>
      {title ? (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-[15px] font-semibold">{title}</h2>
            {subtitle ? <p className="mt-0.5 text-[12.5px] text-[color:var(--nx-muted)]">{subtitle}</p> : null}
          </div>
          {right}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "loss" | "gain" | "warn" }) {
  const color = tone === "loss" ? "text-[color:var(--nx-loss)]" : tone === "gain" ? "text-[color:var(--nx-gain)]" : tone === "warn" ? "text-[color:var(--nx-warn)]" : "text-white";
  return (
    <div className="nx-glass px-4 py-3" data-testid="kpi">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[color:var(--nx-muted)]">{label}</p>
      <p className={`mt-1 text-[22px] font-bold leading-tight tabular-nums ${color}`}>{value}</p>
      {hint ? <p className="mt-0.5 text-[12px] text-[color:var(--nx-muted)]">{hint}</p> : null}
    </div>
  );
}

export function Badge({ children, tone = "info" }: { children: ReactNode; tone?: "official" | "illustrative" | "model" | "info" | "warn" }) {
  const cls = {
    official: "border-emerald-400/50 bg-emerald-400/15 text-emerald-200",
    illustrative: "border-amber-400/50 bg-amber-400/15 text-amber-200",
    model: "border-sky-300/50 bg-sky-400/12 text-sky-200",
    info: "border-white/20 bg-white/8 text-[color:var(--nx-soft)]",
    warn: "border-amber-400/50 bg-amber-400/12 text-amber-200",
  }[tone];
  return <span className={`inline-block rounded-md border px-2 py-0.5 text-[11px] font-bold tracking-wide ${cls}`}>{children}</span>;
}

export function Loading({ what }: { what: string }) {
  return (
    <p role="status" className="flex items-center gap-2 py-8 text-[13px] text-[color:var(--nx-soft)]">
      <Loader2 className="nx-spin h-4 w-4" aria-hidden /> Loading {what}…
    </p>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="nx-glass border-rose-400/40 p-4">
      <p className="flex items-center gap-2 font-semibold text-rose-200">
        <AlertTriangle className="h-4 w-4" aria-hidden /> Something went wrong
      </p>
      <p className="mt-1 text-[13px] text-[color:var(--nx-soft)]">{message}</p>
      {onRetry ? (
        <button type="button" className="nx-chip mt-3" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="mt-2 text-[12px] leading-snug text-[color:var(--nx-muted)]">{children}</p>;
}
