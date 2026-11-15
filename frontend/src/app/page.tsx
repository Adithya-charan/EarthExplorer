import type { Metadata } from "next";
import { ExplorerView } from "@/views/ExplorerView";

export const metadata: Metadata = {
  title: "NASAX Earth Time Machine",
  description: "Search any place on a 3D globe, check what satellite-style observations exist, and see how it changed over time.",
};

export default function Page() {
  return <ExplorerView />;
}
