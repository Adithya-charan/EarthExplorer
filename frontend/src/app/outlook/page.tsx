import type { Metadata } from "next";
import { OutlookView } from "@/views/OutlookView";

export const metadata: Metadata = { title: "Future Outlook" };

export default function Page() {
  return <OutlookView />;
}
