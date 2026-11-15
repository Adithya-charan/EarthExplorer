import type { Metadata } from "next";
import { ChangeAnalyticsView } from "@/views/ChangeAnalyticsView";

export const metadata: Metadata = { title: "Change Analytics" };

export default function Page() {
  return <ChangeAnalyticsView />;
}
