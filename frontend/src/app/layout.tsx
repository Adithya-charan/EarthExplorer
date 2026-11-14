import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { DatasetProvider } from "@/context/DatasetContext";
import { AppShell } from "@/components/shell/AppShell";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: { default: "EarthTrend Explorer", template: "%s · EarthTrend Explorer" },
  description:
    "Explore Earth-science time series: select a variable, region and period, estimate trends with uncertainty, and compare regions. Currently running on clearly labelled synthetic demo data.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full">
        <DatasetProvider>
          <AppShell>{children}</AppShell>
        </DatasetProvider>
      </body>
    </html>
  );
}
