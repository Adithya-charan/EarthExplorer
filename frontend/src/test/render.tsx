import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { DatasetProvider } from "@/context/DatasetContext";
import { AppShell } from "@/components/shell/AppShell";

/** Render a view inside the real dataset provider (the API itself is mocked at the fetch layer). */
export function renderView(ui: ReactElement) {
  return render(<DatasetProvider>{ui}</DatasetProvider>);
}

export function renderInShell(ui: ReactElement) {
  return render(
    <DatasetProvider>
      <AppShell>{ui}</AppShell>
    </DatasetProvider>,
  );
}
