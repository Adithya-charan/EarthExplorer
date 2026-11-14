import type { Metadata } from "next";
import { MethodologyView } from "@/views/MethodologyView";

export const metadata: Metadata = {
  title: "Methodology",
  description: "How trends are estimated and what the results can and cannot show.",
};

export default function Page() {
  return <MethodologyView />;
}
