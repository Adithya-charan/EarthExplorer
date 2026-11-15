import type { Metadata } from "next";
import { CompareView } from "@/views/CompareView";

export const metadata: Metadata = { title: "Compare Places" };

export default function Page() {
  return <CompareView />;
}
