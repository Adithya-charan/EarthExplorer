import type { Metadata } from "next";
import { UploadView } from "@/views/UploadView";

export const metadata: Metadata = {
  title: "Upload Dataset",
  description: "Validate and import a CSV with an explicit column mapping.",
};

export default function Page() {
  return <UploadView />;
}
