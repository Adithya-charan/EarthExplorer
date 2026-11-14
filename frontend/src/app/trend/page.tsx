import type { Metadata } from "next";
import { TrendView } from "@/views/TrendView";

export const metadata: Metadata = {
  title: "Trend Analysis",
  description: "Estimate the direction, size and uncertainty of change in one time series.",
};

export default function Page() {
  return <TrendView />;
}
