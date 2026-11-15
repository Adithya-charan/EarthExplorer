import type { Metadata } from "next";
import { DatasetsView } from "@/views/DatasetsView";

export const metadata: Metadata = { title: "Datasets" };

export default function Page() {
  return <DatasetsView />;
}
