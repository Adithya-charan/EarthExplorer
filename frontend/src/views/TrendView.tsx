"use client";

import { Download } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useAnalysisSelection } from "@/lib/selection";
import { analysisToCsv, downloadText, safeFilePart } from "@/lib/csv";
import type { MetadataResponse } from "@/lib/types";
import { DataGate } from "@/components/data/DataGate";
import { ProvenanceBanner } from "@/components/data/DatasetStatus";
import { AnalysisOptions, DateRangeFilter, SelectField } from "@/components/filters/Fields";
import { DiagnosticsPanel } from "@/components/analysis/DiagnosticsPanel";
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import {
  ExplanationPanel,
  MethodDetails,
  StatisticalResults,
  TrendSummary,
  WarningsList,
} from "@/components/analysis/AnalysisPanels";
import { Button, Card, CardBody, CardHeader, PageHeading } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";

export function TrendView() {
  return (
    <div className="space-y-6">
      <PageHeading
        title="Trend Analysis"
        description="Pick one variable and region to estimate the direction, size and uncertainty of change. The headline test is chosen from the data's own diagnostics."
      />
      <DataGate>{({ metadata, datasetId }) => <TrendBody metadata={metadata} datasetId={datasetId} />}</DataGate>
    </div>
  );
}

function TrendBody({ metadata, datasetId }: { metadata: MetadataResponse; datasetId: string }) {
  const sel = useAnalysisSelection(metadata, datasetId);
  const req = sel.analyzeRequest;
  const analysis = useApi(req ? (signal) => api.analyze(req, signal) : null, req ? JSON.stringify(req) : "");

  const variableMeta = sel.variables.find((v) => v.name === sel.variable);
  const range = metadata.dataset;
  const datesInvalid = Boolean(sel.dates.start && sel.dates.end && sel.dates.start > sel.dates.end);

  return (
    <>
      <ProvenanceBanner provenance={metadata.provenance} />

      <Card aria-labelledby="filters-title">
        <CardHeader id="filters-title" title="Selection" subtitle="Results update automatically when you change a filter." />
        <CardBody>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <SelectField
              id="trend-variable"
              label="Variable"
              value={sel.variable}
              options={sel.variables.map((v) => ({ value: v.name, label: v.units.length ? `${v.name} (${v.units.join(", ")})` : v.name }))}
              onChange={sel.setVariable}
              hint={variableMeta ? `${variableMeta.regions.length} region(s)` : undefined}
            />
            <SelectField
              id="trend-region"
              label="Region"
              value={sel.region}
              options={sel.regionsForVariable.map((r) => ({ value: r, label: r }))}
              onChange={sel.setRegion}
            />
            <DateRangeFilter
              start={sel.dates.start}
              end={sel.dates.end}
              min={range.date_start}
              max={range.date_end}
              onChange={sel.setDates}
            />
            <div className="grid gap-4">
              <AnalysisOptions value={sel.options} onChange={sel.setOptions} idPrefix="trend" />
            </div>
          </div>
        </CardBody>
      </Card>

      {datesInvalid ? (
        <EmptyState title="Fix the date range" description="The start date must be on or before the end date." />
      ) : !req ? (
        <EmptyState title="Choose a variable and region" description="This dataset has no variable/region combination to analyse." />
      ) : analysis.loading ? (
        <div className="space-y-4">
          <LoadingState label="Running analysis" variant="cards" />
          <LoadingState label="Drawing chart" variant="chart" />
        </div>
      ) : analysis.error ? (
        <ErrorState title="Analysis failed" error={analysis.error} onRetry={analysis.reload} />
      ) : analysis.data ? (
        <div className="space-y-6" data-testid="trend-results">
          <TrendSummary analysis={analysis.data} />
          <WarningsList warnings={analysis.data.warnings} />
          <Card aria-labelledby="chart-title">
            <CardHeader
              id="chart-title"
              title="Time series"
              subtitle={`${analysis.data.request.variable} in ${analysis.data.request.region} (${analysis.data.unit || "no unit"})`}
              actions={
                <Button
                  onClick={() =>
                    downloadText(
                      `earthtrend_${safeFilePart(analysis.data!.request.variable)}_${safeFilePart(analysis.data!.request.region)}${analysis.data!.provenance.is_synthetic ? "_SYNTHETIC" : ""}.csv`,
                      analysisToCsv(analysis.data!),
                    )
                  }
                >
                  <Download aria-hidden="true" size={14} /> Export CSV
                </Button>
              }
            />
            <CardBody>
              <TimeSeriesChart analysis={analysis.data} />
            </CardBody>
          </Card>
          <ExplanationPanel explanation={analysis.data.explanation} />
          <StatisticalResults analysis={analysis.data} />
          <DiagnosticsPanel datasetId={datasetId} variable={analysis.data.request.variable} region={analysis.data.request.region} />
          <MethodDetails assumptions={analysis.data.assumptions} />
        </div>
      ) : null}
    </>
  );
}
