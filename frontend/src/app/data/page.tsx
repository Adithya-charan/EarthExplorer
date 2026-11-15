import type { Metadata } from "next";
import { DataMethodsView } from "@/views/DataMethodsView";

export const metadata: Metadata = { title: "Data & Methods" };

export default function Page() {
  return <DataMethodsView />;
}
