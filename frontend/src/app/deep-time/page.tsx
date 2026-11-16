import type { Metadata } from "next";
import { DeepTimeAnalyticsView } from "@/views/DeepTimeAnalyticsView";

export const metadata: Metadata = { title: "Deep-Time Analytics" };

export default function Page() {
  return <DeepTimeAnalyticsView />;
}
