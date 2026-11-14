"use client";

import { useMemo, useState } from "react";
import { useDebouncedValue } from "./hooks";
import type { Aggregation, AnalyzeRequest, CompareRequest, MetadataResponse, SeasonalityMode } from "./types";

export interface AnalysisOptionState {
  aggregation: Aggregation;
  seasonality: SeasonalityMode;
  alpha: number;
}

export const DEFAULT_OPTIONS: AnalysisOptionState = { aggregation: "none", seasonality: "auto", alpha: 0.05 };

/**
 * Variable / region / date / option state for a view. The effective variable and region are
 * derived (falling back to the first valid choice) so the state never points at something the
 * current dataset does not contain, and no effect is needed to "repair" it.
 */
export function useAnalysisSelection(metadata: MetadataResponse | undefined, datasetId: string | null) {
  const [chosenVariable, setVariable] = useState<string | null>(null);
  const [chosenRegion, setRegion] = useState<string | null>(null);
  const [chosenRegions, setRegions] = useState<string[] | null>(null);
  const [dates, setDates] = useState({ start: "", end: "" });
  const [options, setOptions] = useState<AnalysisOptionState>(DEFAULT_OPTIONS);

  const variables = metadata?.variables;
  const variable =
    chosenVariable && variables?.some((v) => v.name === chosenVariable) ? chosenVariable : (variables?.[0]?.name ?? "");
  const regionsForVariable = useMemo(
    () => variables?.find((v) => v.name === variable)?.regions ?? [],
    [variables, variable],
  );
  const region = chosenRegion && regionsForVariable.includes(chosenRegion) ? chosenRegion : (regionsForVariable[0] ?? "");

  // Default comparison: every region carrying the variable, capped to keep the chart readable.
  const regions = useMemo(() => {
    const valid = (chosenRegions ?? []).filter((r) => regionsForVariable.includes(r));
    return chosenRegions === null ? regionsForVariable.slice(0, 4) : valid;
  }, [chosenRegions, regionsForVariable]);

  const debouncedDates = useDebouncedValue(dates, 350);
  const datesValid = !(debouncedDates.start && debouncedDates.end && debouncedDates.start > debouncedDates.end);

  const analyzeRequest: AnalyzeRequest | null =
    datasetId && variable && region && datesValid
      ? {
          dataset_id: datasetId,
          variable,
          region,
          start: debouncedDates.start || null,
          end: debouncedDates.end || null,
          ...options,
        }
      : null;

  const compareRequest: CompareRequest | null =
    datasetId && variable && regions.length >= 2 && datesValid
      ? {
          dataset_id: datasetId,
          variable,
          regions,
          start: debouncedDates.start || null,
          end: debouncedDates.end || null,
          ...options,
        }
      : null;

  return {
    variables: variables ?? [],
    variable,
    setVariable,
    regionsForVariable,
    region,
    setRegion,
    regions,
    setRegions,
    dates,
    setDates,
    options,
    setOptions,
    analyzeRequest,
    compareRequest,
  };
}
