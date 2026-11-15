import type { Metadata } from "next";
import { StoryView } from "@/views/StoryView";

export const metadata: Metadata = {
  title: "What happened here?",
  description: "Pick a place and a time, read a data-backed summary, and see it on a 3D map.",
};

export default function Page() {
  return <StoryView />;
}
