import Icon from "./Icon";
import ModelMark from "./ModelMark";
import {
  names,
  priorities,
  teamLabel,
  type Ticket,
  type Provider,
  type Analysis,
  type Health,
} from "../lib/tickets";

type Props = {
  ticket: Ticket;
  modelHealth: (provider: Provider) => Health;
  isStale: (ticket: Ticket, provider: Provider) => boolean;
  busy: { id: string; provider: Provider } | null;
  locked: boolean;
  onAnalyze: (id: string, provider: Provider) => Promise<boolean>;
};
export default function ModelComparison({
  ticket: t,
  modelHealth,
  isStale,
  busy,
  locked,
  onAnalyze: analyze,
}: Props) {
  const left = t.runs["laya-ft"].analysis,
    right = t.runs.jev.analysis;
  const comparable =
    left &&
    right &&
    !!modelHealth("laya-ft").model &&
    !!modelHealth("jev").model &&
    !isStale(t, "laya-ft") &&
    !isStale(t, "jev") &&
    left.input_id === right.input_id;
  const rows: { label: string; value: (a: Analysis) => string }[] = [
    { label: "Team", value: (a) => teamLabel(a.suggested_team) },
    {
      label: "Priority",
      value: (a) => `${a.priority} · ${priorities[a.priority] || a.priority}`,
    },
    { label: "Complaint", value: (a) => (a.complaint >= 0.5 ? "Yes" : "No") },
    { label: "Churn risk", value: (a) => (a.churn >= 0.5 ? "Yes" : "No") },
    { label: "Refund", value: (a) => (a.refund >= 0.5 ? "Yes" : "No") },
  ];
  const differences = comparable
    ? rows.filter((row) => row.value(left) !== row.value(right)).length
    : 0;
  return (
    <div className="comparison-page workspace-scroll">
      <div className="comparison-heading">
        <span className="eyebrow">SIDE BY SIDE</span>
        <h2>Two models. One ticket.</h2>
        <p>Compare the five signals side by side.</p>
      </div>
      <div className="comparison-context">
        <Icon name="document" />
        <div>
          <small>{t.id}</small>
          <strong>{t.subject}</strong>
        </div>
      </div>
      <div className="comparison-models">
        {(["laya-ft", "jev"] as Provider[]).map((p) => {
          const a = t.runs[p].analysis,
            old = isStale(t, p),
            processing = busy?.id === t.id && busy.provider === p;
          return (
            <section
              className={`comparison-model ${p === "jev" ? "jev-card" : "laya-card"}`}
              key={p}
            >
              <div className="model-card-heading">
                <ModelMark provider={p} />
                <div>
                  <h3>{names[p]}</h3>
                  <p>{p === "jev" ? "Cloud API" : "Local · V5"}</p>
                </div>
                <span
                  className={`status-dot ${modelHealth(p).status}`}
                  title={modelHealth(p).message}
                />
              </div>
              <div className="model-card-state">
                <span>
                  {processing
                    ? "Analyzing…"
                    : a
                      ? old
                        ? "Outdated"
                        : "Done"
                      : "Pending"}
                </span>
                <small>
                  {a ? `${(a.elapsed_ms / 1000).toFixed(1)} s` : "—"}
                </small>
              </div>
              <button
                className="button secondary full-width"
                disabled={
                  locked ||
                  modelHealth(p).status !== "ready" ||
                  ["assigned", "done"].includes(t.runs[p].status)
                }
                onClick={() => void analyze(t.id, p)}
              >
                <Icon
                  name={processing ? "refresh" : "sparkles"}
                  size={16}
                  className={processing ? "spin" : ""}
                />
                {t.runs[p].status === "done" ? "Done" : t.runs[p].status === "assigned"
                  ? "Assigned"
                  : processing
                    ? "Analyzing"
                    : a
                      ? "Analyze again"
                      : `Analyze`}
              </button>
            </section>
          );
        })}
      </div>
      <div
        className={`comparison-verdict ${comparable && differences ? "has-differences" : ""}`}
      >
        <Icon
          name={comparable && !differences ? "check" : "compare"}
          size={18}
        />
        {comparable
          ? differences
            ? `${differences} differences. Review before assigning.`
            : "All five signals agree. Review before assigning."
          : "Analyze with both models to compare."}
      </div>
      <div className="comparison-table-wrap">
        <table className="comparison-table">
          <thead>
            <tr>
              <th>Signal</th>
              <th>
                Laya <small>Local</small>
              </th>
              <th>
                Jev <small>API</small>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.label}
                className={
                  comparable && row.value(left) !== row.value(right)
                    ? "different"
                    : ""
                }
              >
                <th scope="row">{row.label}</th>
                {[left, right].map((a, i) => (
                  <td key={i}>
                    {a ? row.value(a) : <span className="muted">Pending</span>}
                    {a && isStale(t, i === 0 ? "laya-ft" : "jev") && (
                      <small className="old-result">Outdated</small>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="panel-footnote">
        <Icon name="cloud" size={15} />
        Jev sends this ticket to its API. Fees apply. Matching results still need review.
      </p>
    </div>
  );
}
