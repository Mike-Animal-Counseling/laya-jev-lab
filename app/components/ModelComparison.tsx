import Icon from "./Icon";
import ModelMark from "./ModelMark";
import {
  names,
  priorities,
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
    { label: "负责团队", value: (a) => a.suggested_team },
    {
      label: "紧急程度",
      value: (a) => `${a.priority} · ${priorities[a.priority] || a.priority}`,
    },
    { label: "投诉倾向", value: (a) => (a.complaint >= 0.5 ? "有" : "无") },
    { label: "流失风险", value: (a) => (a.churn >= 0.5 ? "有" : "无") },
    { label: "退款诉求", value: (a) => (a.refund >= 0.5 ? "有" : "无") },
  ];
  const differences = comparable
    ? rows.filter((row) => row.value(left) !== row.value(right)).length
    : 0;
  return (
    <div className="comparison-page workspace-scroll">
      <div className="comparison-heading">
        <span className="eyebrow">SIDE BY SIDE</span>
        <h2>同一张工单，两种判断。</h2>
        <p>并排查看本地微调模型与 API 模型的五项结果。</p>
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
                  <p>{p === "jev" ? "云端 API" : "本地微调 · V5"}</p>
                </div>
                <span
                  className={`status-dot ${modelHealth(p).status}`}
                  title={modelHealth(p).message}
                />
              </div>
              <div className="model-card-state">
                <span>
                  {processing
                    ? "正在分析…"
                    : a
                      ? old
                        ? "结果待更新"
                        : "分析已完成"
                      : "尚未分析"}
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
                  t.runs[p].status === "assigned"
                }
                onClick={() => void analyze(t.id, p)}
              >
                <Icon
                  name={processing ? "refresh" : "sparkles"}
                  size={16}
                  className={processing ? "spin" : ""}
                />
                {t.runs[p].status === "assigned"
                  ? "已分配 · 结果已保留"
                  : processing
                    ? "分析中"
                    : a
                      ? "重新分析"
                      : `使用 ${names[p]} 分析`}
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
            ? `有 ${differences} 项判断不同，建议人工核对。`
            : "五项判断一致，仍需结合工单内容确认。"
          : "完成两侧的当前版本分析后，即可查看判断差异。"}
      </div>
      <div className="comparison-table-wrap">
        <table className="comparison-table">
          <thead>
            <tr>
              <th>判断维度</th>
              <th>
                Laya <small>本地</small>
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
                    {a ? row.value(a) : <span className="muted">待分析</span>}
                    {a && isStale(t, i === 0 ? "laya-ft" : "jev") && (
                      <small className="old-result">旧结果</small>
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
        点击 Jev 分析会发送本工单标题与正文，并产生 API
        调用费用。结果一致不代表一定正确。
      </p>
    </div>
  );
}
