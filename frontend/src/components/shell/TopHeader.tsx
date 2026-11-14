"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CircleHelp, Menu } from "lucide-react";
import { useDatasets } from "@/context/DatasetContext";
import { DatasetSelector } from "@/components/data/DatasetSelector";
import { DatasetStatus } from "@/components/data/DatasetStatus";
import { Skeleton } from "@/components/ui/states";
import { navFor } from "./nav";

export function TopHeader({ onMenu }: { onMenu: () => void }) {
  const pathname = usePathname();
  const page = navFor(pathname);
  const { selected, listLoading } = useDatasets();

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
      <div className="flex min-h-14 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 sm:px-6">
        <button
          type="button"
          onClick={onMenu}
          aria-label="Open navigation"
          className="-ml-1 rounded-md p-2 text-ink-soft hover:bg-surface-muted lg:hidden"
        >
          <Menu size={20} aria-hidden="true" />
        </button>
        <div className="min-w-0 flex-1 basis-48">
          <p className="truncate text-sm font-semibold text-ink">{page.title}</p>
          <p className="hidden truncate text-xs text-muted sm:block">{page.description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {listLoading ? (
            <Skeleton className="h-6 w-40" />
          ) : selected ? (
            <DatasetStatus status={selected.status} isSynthetic={selected.is_synthetic} />
          ) : null}
          <DatasetSelector />
          <Link
            href="/methodology"
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-ink-soft hover:bg-surface-muted"
          >
            <CircleHelp size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Methodology</span>
            <span className="sr-only sm:hidden">Methodology and help</span>
          </Link>
        </div>
      </div>
      {selected?.is_synthetic ? (
        <p
          role="note"
          data-testid="synthetic-strip"
          className="border-t border-warn-line bg-warn-soft px-4 py-1 text-center text-xs font-semibold tracking-wide text-warn sm:px-6"
        >
          {selected.status === "synthetic_regional_demo"
            ? "SYNTHETIC DEMO — NOT NASA OBSERVATIONS"
            : "SYNTHETIC DEMO DATA — NOT REAL OBSERVATIONS"}
        </p>
      ) : null}
    </header>
  );
}
