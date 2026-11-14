"use client";

import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Table2 } from "lucide-react";
import type { AnalyzeResponse } from "@/lib/types";
import { COLORS } from "@/lib/palette";
import { usePrefersReducedMotion } from "@/lib/hooks";
import { fmtDate, fmtNum, sourceLabelFor } from "@/lib/format";
import { toEpoch, yearLabel, yearTicks } from "@/lib/ticks";
import { ChartSourceTag } from "@/components/data/DatasetStatus";
import { Button } from "@/components/ui/primitives";

interface Row {
  t: number;
  date: string;
  value: number | null;
  ols: number | null;
  sen: number | null;
  deseason: number | null;
}


export function ChartTooltip({
  active,
  payload,
  unit,
  region,
  variable,
  sourceLabel,
}: {
  active?: boolean;
  payload?: { payload: Row }[];
  unit: string;
  region: string;
  variable: string;
  sourceLabel: string;
}) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-md border border-line-strong bg-surface px-3 py-2 text-xs shadow-card">
      <p className="font-semibold text-ink">{fmtDate(r.date)}</p>
      <p className="text-muted">
        {variable} · {region}
      </p>
      <dl className="mt-1.5 space-y-0.5">
        <Row label="Value" v={r.value} unit={unit} />
        <Row label="OLS fit" v={r.ols} unit={unit} />
        <Row label="Sen fit" v={r.sen} unit={unit} />
        <Row label="Deseasonalized" v={r.deseason} unit={unit} />
      </dl>
      <p className="mt-1.5 border-t border-line pt-1 text-muted">{sourceLabel}</p>
    </div>
  );
}

function Row({ label, v, unit }: { label: string; v: number | null; unit: string }) {
  if (v === null) return null;
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="tabular font-medium text-ink">
        {fmtNum(v, 5)} {unit}
      </dd>
    </div>
  );
}

export function TimeSeriesChart({ analysis }: { analysis: AnalyzeResponse }) {
  const reduced = usePrefersReducedMotion();
  const [showOls, setShowOls] = useState(true);
  const [showSen, setShowSen] = useState(true);
  const [showDeseason, setShowDeseason] = useState(false);
  const [showTable, setShowTable] = useState(false);

  const { points, unit, request, provenance } = analysis;
  const hasDeseason = points.some((p) => p.deseasonalized !== null);
  const hasOls = points.some((p) => p.fitted_ols !== null);
  const hasSen = points.some((p) => p.fitted_sen !== null);

  const data = useMemo<Row[]>(
    () =>
      points.map((p) => ({
        t: toEpoch(p.date),
        date: p.date,
        value: p.value,
        ols: p.fitted_ols,
        sen: p.fitted_sen,
        deseason: p.deseasonalized,
      })),
    [points],
  );
  const showDots = data.filter((d) => d.value !== null).length <= 80;
  const ticks = useMemo(() => yearTicks(data[0]?.t ?? NaN, data.at(-1)?.t ?? NaN), [data]);
  const sourceLabel = sourceLabelFor(provenance);
  const ariaLabel = `Time series of ${request.variable} in ${request.region}, ${analysis.coverage.n_valid} valid observations from ${fmtDate(analysis.coverage.first_date)} to ${fmtDate(analysis.coverage.last_date)}. ${sourceLabel}.`;

  return (
    <figure aria-label={ariaLabel} className="m-0">
      <ChartSourceTag provenance={provenance} />
      <div className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <Toggle id="tog-ols" label="OLS fit" checked={showOls} onChange={setShowOls} disabled={!hasOls} color={COLORS.ols} />
        <Toggle id="tog-sen" label="Sen's line" checked={showSen} onChange={setShowSen} disabled={!hasSen} color={COLORS.sen} />
        <Toggle
          id="tog-deseason"
          label="Deseasonalized (descriptive)"
          checked={showDeseason}
          onChange={setShowDeseason}
          disabled={!hasDeseason}
          color={COLORS.deseasonalized}
        />
        <Button className="ml-auto" onClick={() => setShowTable((s) => !s)} aria-pressed={showTable}>
          <Table2 aria-hidden="true" size={14} /> {showTable ? "Hide data table" : "Show data table"}
        </Button>
      </div>

      <div className="h-[340px] w-full sm:h-[380px]" data-testid="trend-chart">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 4 }}>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              ticks={ticks.length ? ticks : undefined}
              tickFormatter={yearLabel}
              stroke={COLORS.axis}
              tick={{ fontSize: 12 }}
              minTickGap={24}
            />
            <YAxis
              stroke={COLORS.axis}
              tick={{ fontSize: 12 }}
              width={64}
              tickFormatter={(v: number) => fmtNum(v, 3)}
              domain={["auto", "auto"]}
              label={{ value: unit, angle: -90, position: "insideLeft", offset: 4, style: { fontSize: 12, fill: COLORS.axis } }}
            />
            <Tooltip
              content={
                <ChartTooltip unit={unit} region={request.region} variable={request.variable} sourceLabel={sourceLabel} />
              }
            />
            <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12 }} />
            <Line
              name="Observed"
              dataKey="value"
              stroke={COLORS.observed}
              strokeWidth={1.75}
              dot={showDots ? { r: 2.5 } : false}
              activeDot={{ r: 4 }}
              connectNulls={false}
              isAnimationActive={!reduced}
            />
            {showDeseason && hasDeseason ? (
              <Line
                name="Deseasonalized"
                dataKey="deseason"
                stroke={COLORS.deseasonalized}
                strokeDasharray="2 3"
                strokeWidth={1.75}
                dot={false}
                connectNulls={false}
                isAnimationActive={!reduced}
              />
            ) : null}
            {showOls && hasOls ? (
              <Line
                name="OLS fit"
                dataKey="ols"
                stroke={COLORS.ols}
                strokeDasharray="7 3"
                strokeWidth={2}
                dot={false}
                isAnimationActive={!reduced}
              />
            ) : null}
            {showSen && hasSen ? (
              <Line
                name="Sen's line"
                dataKey="sen"
                stroke={COLORS.sen}
                strokeDasharray="9 3 2 3"
                strokeWidth={2}
                dot={false}
                isAnimationActive={!reduced}
              />
            ) : null}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="mt-1 text-xs text-muted">
        {sourceLabel}. Gaps in the line are missing values; nothing is interpolated. Fitted lines describe the selected
        window only.
      </figcaption>

      {showTable ? (
        <div className="mt-3 max-h-72 overflow-auto rounded-md border border-line" tabIndex={0} aria-label="Chart data table">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">
              Values plotted in the chart, in {unit}
            </caption>
            <thead className="sticky top-0 bg-surface-muted text-xs text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">
                  Date
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  Value ({unit})
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  OLS fit
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  Sen fit
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.date} className="border-t border-line">
                  <td className="tabular px-3 py-1.5">{fmtDate(r.date)}</td>
                  <td className="tabular px-3 py-1.5 text-right">{r.value === null ? "missing" : fmtNum(r.value, 5)}</td>
                  <td className="tabular px-3 py-1.5 text-right">{fmtNum(r.ols, 5)}</td>
                  <td className="tabular px-3 py-1.5 text-right">{fmtNum(r.sen, 5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </figure>
  );
}

function Toggle({
  id,
  label,
  checked,
  onChange,
  disabled,
  color,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  color: string;
}) {
  return (
    <label htmlFor={id} className={`inline-flex items-center gap-2 ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4 accent-[#0f766e]"
        checked={checked && !disabled}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span aria-hidden="true" className="inline-block h-0.5 w-4" style={{ background: color }} />
      {label}
    </label>
  );
}
