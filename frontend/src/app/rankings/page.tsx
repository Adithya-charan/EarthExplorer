import type { Metadata } from "next";
import { RankingsView } from "@/views/RankingsView";

export const metadata: Metadata = { title: "Rankings & Map" };

export default function Page() {
  return <RankingsView />;
}
