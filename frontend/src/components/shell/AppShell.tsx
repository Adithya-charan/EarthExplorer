"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { TopHeader } from "./TopHeader";

export function AppShell({ children }: { children: ReactNode }) {
  const [openForPath, setOpenForPath] = useState<string | null>(null);
  const pathname = usePathname();
  // The drawer is tied to the path it was opened on, so navigating closes it without an effect.
  const open = openForPath === pathname;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenForPath(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // The Earth Time Machine is a full-screen scene with its own controls; every other page keeps the standard shell.
  if (pathname === "/") return <>{children}</>;

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to main content
      </a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-line lg:block" aria-label="Sidebar">
        <Sidebar />
      </aside>

      {/* Mobile / tablet drawer */}
      {open ? (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-ink/40"
            onClick={() => setOpenForPath(null)}
          />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] shadow-xl">
            <Sidebar mobile onNavigate={() => setOpenForPath(null)} onClose={() => setOpenForPath(null)} />
          </div>
        </div>
      ) : null}

      <div className="lg:pl-60">
        <TopHeader onMenu={() => setOpenForPath(pathname)} />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:py-8">
          {children}
        </main>
        <footer className="border-t border-line px-4 py-4 text-xs text-muted sm:px-6">
            EarthTrend Explorer · Statistical exploration tool. Results describe the selected data only and do not establish
            causes. Explanations are rule-based; no external AI service is used.
          </footer>
      </div>
    </div>
  );
}
