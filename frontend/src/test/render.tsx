import { render } from "@testing-library/react";
import type { ReactElement } from "react";

/** Render a view (the API itself is mocked at the fetch layer, see mockApi.ts). */
export function renderView(ui: ReactElement) {
  return render(ui);
}
