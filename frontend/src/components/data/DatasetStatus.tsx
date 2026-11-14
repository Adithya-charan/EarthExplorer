import { FlaskConical, Globe2, ShieldCheck, UploadCloud } from "lucide-react";
import type { DatasetStatus as Status, Provenance } from "@/lib/types";
import { DATASET_STATUS_LABEL, sourceLabelFor } from "@/lib/format";
import { Badge, Callout } from "@/components/ui/primitives";

const TONE = {
  synthetic_demo: "warn",
  uploaded: "info",
  nasa_verified: "accent",
  observed_global: "accent",
  synthetic_regional_demo: "warn",
} as const;
const ICON = {
  observed_global: <Globe2 aria-hidden="true" size={13} />,
  synthetic_regional_demo: <FlaskConical aria-hidden="true" size={13} />,
  synthetic_demo: <FlaskConical aria-hidden="true" size={13} />,
  uploaded: <UploadCloud aria-hidden="true" size={13} />,
  nasa_verified: <ShieldCheck aria-hidden="true" size={13} />,
};

/** Status chip: Synthetic Demo / Uploaded Dataset / NASA Dataset (only ever shown for a verified dataset). */
export function DatasetStatus({ status, isSynthetic }: { status: Status; isSynthetic?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5" data-testid="dataset-status">
      <Badge tone={TONE[status]}>
        {ICON[status]}
        {DATASET_STATUS_LABEL[status]}
      </Badge>
      {status !== "synthetic_demo" && status !== "synthetic_regional_demo" && isSynthetic ? (
        <Badge tone="warn">
          <FlaskConical aria-hidden="true" size={13} />
          Contains synthetic rows
        </Badge>
      ) : null}
    </span>
  );
}

/**
 * Visible provenance banner. Shown wherever data are viewed or analysed:
 * a strong amber notice for synthetic data, a neutral note for unverified uploads.
 */
export function ProvenanceBanner({ provenance }: { provenance: Provenance | undefined }) {
  if (!provenance) return null;
  if (provenance.status === "observed_global") {
    return (
      <Callout tone="info" role="note" icon={<Globe2 size={18} />} title="Observed global data">
        <span data-testid="observed-global-banner">
          {provenance.notice ?? "Global area-averaged NASA series. It is not regional and cannot support regional claims."}
        </span>
      </Callout>
    );
  }
  if (provenance.is_synthetic) {
    return (
      <Callout
        tone="warn"
        role="note"
        icon={<FlaskConical size={18} />}
        title={provenance.status === "synthetic_regional_demo" ? "SYNTHETIC DEMO — NOT NASA OBSERVATIONS" : "Synthetic demo data"}
      >
        <span data-testid="synthetic-banner">
          {provenance.notice ??
            "These values are artificial and were generated for demonstration. They are not observations."}
        </span>
      </Callout>
    );
  }
  if (provenance.status === "uploaded") {
    return (
      <Callout tone="info" role="note" icon={<UploadCloud size={18} />} title="Uploaded dataset">
        {provenance.notice ?? "Provenance is declared by the uploader and is not verified."}
      </Callout>
    );
  }
  return null;
}

/** One-line tag printed on top of every chart so a screenshot of it still carries its data class. */
export function ChartSourceTag({ provenance }: { provenance: Provenance }) {
  if (!provenance.is_synthetic && provenance.status !== "observed_global") return null;
  const synthetic = provenance.is_synthetic;
  return (
    <p
      data-testid={synthetic ? "chart-synthetic-tag" : "chart-observed-tag"}
      className={
        synthetic
          ? "mb-2 inline-block rounded border border-warn-line bg-warn-soft px-2 py-0.5 text-xs font-semibold tracking-wide text-warn"
          : "mb-2 inline-block rounded border border-line bg-surface-muted px-2 py-0.5 text-xs font-medium text-ink-soft"
      }
    >
      {sourceLabelFor(provenance)}
    </p>
  );
}
