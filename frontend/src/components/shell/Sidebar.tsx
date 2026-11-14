"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Globe2, X } from "lucide-react";
import { NAV } from "./nav";
import { useDatasets } from "@/context/DatasetContext";
import { cx } from "@/components/ui/primitives";

export function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5 rounded-md" aria-label="EarthTrend Explorer home">
      <span
        aria-hidden="true"
        className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-white"
      >
        <Globe2 size={18} />
      </span>
      <span className="text-[15px] font-semibold tracking-tight text-ink">
        EarthTrend <span className="text-accent">Explorer</span>
      </span>
    </Link>
  );
}

export function Sidebar({ onNavigate, onClose, mobile }: { onNavigate?: () => void; onClose?: () => void; mobile?: boolean }) {
  const pathname = usePathname();
  const { list } = useDatasets();
  return (
    <div className="flex h-full flex-col bg-surface">
      <div className="flex h-14 items-center justify-between border-b border-line px-4">
        <Brand />
        {mobile ? (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="rounded-md p-1.5 text-muted hover:bg-surface-muted"
          >
            <X size={18} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="space-y-0.5">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "bg-accent-soft text-accent-strong"
                      : "text-ink-soft hover:bg-surface-muted hover:text-ink",
                  )}
                >
                  <Icon aria-hidden="true" size={17} className={active ? "text-accent" : "text-muted"} />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="border-t border-line px-4 py-3 text-xs text-muted">
        <p className="font-medium text-ink-soft">Data status</p>
        <p className="mt-0.5" data-testid="sidebar-data-status">
          {!list
            ? "Checking dataset status…"
            : list.nasa_dataset.integrated
              ? "A verified NASA dataset is loaded."
              : list.datasets.some((d) => d.status === "observed_global")
                ? "Observed NASA data are global only. Regional series are synthetic demo data; real regional analysis is disabled."
                : "No NASA dataset is integrated yet. The demo data are synthetic."}
        </p>
      </div>
    </div>
  );
}
