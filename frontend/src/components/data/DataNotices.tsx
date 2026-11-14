"use client";

import { useDatasets } from "@/context/DatasetContext";
import { Callout } from "@/components/ui/primitives";

/** Honest status notices that must stay visible on the main page: NASA status, regional limits, load problems. */
export function DataNotices() {
  const { list, selected } = useDatasets();
  if (!list) return null;
  const issues = list.package_issues ?? [];
  const regionalOff = selected?.info?.regional_analysis_allowed === false;
  const noRealRegional = !list.datasets.some((d) => d.status === "nasa_verified");
  return (
    <div className="space-y-2">
      <p data-testid="nasa-status" className="text-xs text-muted">
        {list.nasa_dataset.message}
      </p>
      {noRealRegional ? (
        <Callout tone="info" role="note">
          <span data-testid="regional-disabled">
            No regional NASA observations have been supplied. Regional places on the map come from clearly labelled synthetic demo data
            or from datasets you upload yourself; observed global data is never shown as a region.
            {regionalOff ? " The selected dataset is a global average, so only the whole-world series is available." : ""}
          </span>
        </Callout>
      ) : null}
      {issues.length ? (
        <Callout tone="warn" role="alert" title="Some bundled data could not be loaded">
          <ul data-testid="package-issues" className="list-disc pl-4">
            {issues.map((i, n) => (
              <li key={`${i.code}-${n}`}>{i.message}</li>
            ))}
          </ul>
        </Callout>
      ) : null}
    </div>
  );
}
