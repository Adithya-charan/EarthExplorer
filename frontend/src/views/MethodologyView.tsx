"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Callout, Card, CardBody, CardHeader, PageHeading } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";

export function MethodologyView() {
  const { data, error, loading, reload } = useApi((signal) => api.methodology(signal), "methodology");

  return (
    <div className="space-y-6">
      <PageHeading
        title="Methodology / About"
        description="How trends are estimated, how the headline test is chosen, and what these numbers cannot tell you."
      />

      <Callout tone="warn" role="note" title="Read this first">
        Results are statistical descriptions of the selected data. They do not show what caused a change, they have not been
        scientifically validated against any NASA product. The observed NASA series are global averages and say nothing about any region, and the bundled regional and demo series are synthetic.
      </Callout>

      {loading ? (
        <LoadingState label="Loading methodology" variant="block" />
      ) : error ? (
        <ErrorState title="Could not load methodology" error={error} onRetry={reload} />
      ) : data ? (
        <>
          {data.sections.map((s) => (
            <Card key={s.id} aria-labelledby={`m-${s.id}`}>
              <CardHeader id={`m-${s.id}`} title={s.title} />
              <CardBody className="space-y-2 text-sm text-ink-soft">
                {s.body.map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </CardBody>
            </Card>
          ))}

          <Card aria-labelledby="m-defaults">
            <CardHeader id="m-defaults" title="Default parameters" subtitle="Fixed in the backend; shown here so results can be reproduced." />
            <CardBody>
              <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(data.defaults).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3 border-b border-line py-1">
                    <dt className="text-muted">{k.replace(/_/g, " ")}</dt>
                    <dd className="tabular font-medium text-ink">{v}</dd>
                  </div>
                ))}
              </dl>
            </CardBody>
          </Card>

          <Card aria-labelledby="m-refs">
            <CardHeader id="m-refs" title="References" />
            <CardBody>
              <ul className="list-disc space-y-2 pl-5 text-sm text-ink-soft">
                {data.references.map((r) => (
                  <li key={r.citation}>
                    {r.citation}
                    {r.url ? (
                      <>
                        {" "}
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="break-all text-accent underline"
                        >
                          {r.url}
                        </a>
                      </>
                    ) : null}
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </>
      ) : null}
    </div>
  );
}
