import { BarChart3, BookOpen, Globe2, History, UploadCloud, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  title: string;
  description: string;
  icon: LucideIcon;
}

export const NAV: NavItem[] = [
  {
    href: "/",
    label: "Earth Time Machine",
    title: "NASAX Earth Time Machine",
    description: "Search a place on the 3D globe and see how it changed over time.",
    icon: History,
  },
  {
    href: "/story",
    label: "What happened?",
    title: "What happened here?",
    description: "Pick a place and a time, read the summary, see it on a 3D map, or ask in chat.",
    icon: Globe2,
  },
  {
    href: "/trend",
    label: "Trend Analysis",
    title: "Trend Analysis",
    description: "Estimate the direction, size and uncertainty of change in one series.",
    icon: BarChart3,
  },
  {
    href: "/upload",
    label: "Upload Dataset",
    title: "Upload Dataset",
    description: "Validate and import a CSV with an explicit column mapping.",
    icon: UploadCloud,
  },
  {
    href: "/methodology",
    label: "Methodology / About",
    title: "Methodology / About",
    description: "How the statistics work, and what they cannot tell you.",
    icon: BookOpen,
  },
];

export function navFor(pathname: string): NavItem {
  const exact = NAV.find((n) => n.href === pathname);
  if (exact) return exact;
  return NAV.find((n) => n.href !== "/" && pathname.startsWith(n.href)) ?? NAV[0];
}
