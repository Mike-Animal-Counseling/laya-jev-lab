"use client";

import { useEffect, useRef, useState } from "react";
import { request } from "../lib/api";

type Summary = {
  tickets: number;
  categories: Record<string, number>;
  splits: Record<string, number>;
  trained_fields: string[];
  unchanged_fields: string[];
  redacted_fields: number;
  missing_categories: string[];
};
type Metric = {
  n: number;
  accuracy: number;
  macro_f1: number;
  per_class: Record<
    string,
    { n: number; precision: number; recall: number; f1: number }
  >;
};
type Evaluation = {
  baseline: Record<string, Metric>;
  candidate: Record<string, Metric>;
  recommended: boolean;
  test_tickets: number;
  trained_fields: string[];
};
type Job = {
  id: string;
  status: string;
  phase: string;
  created: number;
  summary: Summary;
  evaluation: Evaluation | null;
  error: string | null;
  kernel_url: string;
  dataset_url: string;
};
type TrainingStatus = {
  connector_available: boolean;
  connected: boolean;
  username: string;
  active_model: string | null;
  jobs: Job[];
};
type Preview = { dataset_id: string; summary: Summary };
const activeStates = new Set([
  "queued",
  "working",
  "running",
  "uncertain",
  "paused",
]);
const categoryNames = ["Billing", "Technical", "Sales", "Account", "Other"];
const phaseNames: Record<string, string> = {
  upload: "Preparing data",
  dataset: "Preparing on Kaggle",
  submit: "Starting GPU",
  poll: "Training on Kaggle",
  download: "Checking model",
  complete: "Ready",
};
const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

export default function TrainLaya() {
  const [data, setData] = useState<TrainingStatus | null>(null);
  const [username, setUsername] = useState("");
  const [token, setToken] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [fileName, setFileName] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const requestId = useRef<string | null>(null);
  const inFlight = useRef(false);

  async function refresh() {
    const value = await request<TrainingStatus>("training", "laya-ft");
    setData(value);
    return value;
  }
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const value = await request<TrainingStatus>("training", "laya-ft");
        if (alive) setData(value);
      } catch (e) {
        if (alive) setError((e as Error).message);
      } finally {
        inFlight.current = false;
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 10000);
    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, []);

  async function act(path: string, body: object, message: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request(path, "laya-ft", body);
      await refresh();
      setNotice(message);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function upload(file: File | undefined) {
    if (!file) return;
    setPreview(null);
    setConsent(false);
    requestId.current = null;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (!/\.(csv|xlsx)$/i.test(file.name) || file.size > 2 * 1024 * 1024)
        throw new Error("Choose a CSV or Excel file up to 2 MB.");
      const value = await request<Preview>("training/preview", "laya-ft", file);
      setPreview(value);
      setFileName(file.name);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function train() {
    if (!preview || !consent) return;
    requestId.current ||= window.crypto.randomUUID();
    if (
      await act(
        "training/start",
        {
          dataset_id: preview.dataset_id,
          request_id: requestId.current,
          confirm_upload: true,
        },
        "Training requested. You can leave this page.",
      )
    ) {
      setPreview(null);
      setConsent(false);
      requestId.current = null;
    }
  }
  const running =
    data?.jobs.some((job) => activeStates.has(job.status)) || false;
  return (
    <div className="train-layout">
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="settings-notice" role="status">
          {notice}
        </p>
      )}
      <section className="settings-card train-intro">
        <div>
          <p className="eyebrow">Your tickets. Your model.</p>
          <h2>Train Laya</h2>
          <p>
            Adapt Laya V5 to your labelled tickets. Train on your Kaggle GPU,
            compare results, then choose your model.
          </p>
        </div>
        <span className="quiet-tag">V5 + your data</span>
      </section>
      {!data ? (
        <p className="settings-empty">Loading training…</p>
      ) : (
        <>
          {!data.connector_available && (
            <p className="settings-notice">
              The Kaggle connector needs to be installed by your operator. Data
              preview is available.
            </p>
          )}
          <div className="settings-grid">
            <section className="settings-card">
              <div className="settings-card-heading">
                <h2>Kaggle</h2>
                <span
                  className={data.connected ? "connected-tag" : "quiet-tag"}
                >
                  {data.connected ? "Connected" : "Connect once"}
                </span>
              </div>
              <p>
                {data.connected
                  ? `Connected as ${data.username}. Training uses this account’s GPU quota.`
                  : "Use your own account and GPU quota. Your token stays in this workspace."}
              </p>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (
                    await act(
                      "training/connect",
                      { username, api_token: token },
                      "Kaggle connected",
                    )
                  )
                    setToken("");
                }}
              >
                <label>
                  Username
                  <input
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value.toLowerCase())}
                    maxLength={30}
                    autoComplete="off"
                    placeholder={data.username || "Kaggle username"}
                  />
                </label>
                <label>
                  API token
                  <input
                    required
                    type="password"
                    autoComplete="new-password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    maxLength={4096}
                  />
                </label>
                <div className="settings-actions">
                  <button
                    className="button secondary"
                    disabled={busy || running || !data.connector_available}
                  >
                    {busy
                      ? "Working…"
                      : data.connected
                        ? "Update connection"
                        : "Connect"}
                  </button>
                  <a
                    className="train-text-link"
                    href="https://www.kaggle.com/settings/api"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Get token ↗
                  </a>
                </div>
              </form>
              {data.connected && (
                <button
                  className="button secondary"
                  disabled={busy || running}
                  onClick={() =>
                    void act(
                      "training/disconnect",
                      {},
                      "Kaggle token removed. Your model is kept.",
                    )
                  }
                >
                  Disconnect
                </button>
              )}
            </section>
            <section className="settings-card">
              <div className="settings-card-heading">
                <h2>Training data</h2>
                <a className="train-text-link" href="/api/training/template">
                  CSV template ↓
                </a>
              </div>
              <p>
                CSV or Excel with subject, message and category. At least two
                categories, with 10 conversation groups each. Optional labels:
                urgency, complaint, churn and refund.
              </p>
              <label className="train-upload">
                {fileName || "Choose CSV or Excel"}
                <input
                  type="file"
                  accept=".csv,.xlsx"
                  disabled={busy || running}
                  onChange={(e) => void upload(e.target.files?.[0])}
                />
              </label>
              {preview && (
                <div className="train-preview">
                  <div className="train-counts">
                    <span>
                      <strong>{preview.summary.tickets}</strong>Tickets
                    </span>
                    <span>
                      <strong>{preview.summary.splits.test}</strong>Held out
                    </span>
                    <span>
                      <strong>{preview.summary.redacted_fields}</strong>Fields
                      masked
                    </span>
                  </div>
                  <p>
                    Trains {preview.summary.trained_fields.join(", ")}.{" "}
                    {preview.summary.unchanged_fields.length > 0 &&
                      `Keeps ${preview.summary.unchanged_fields.join(", ")} on V5.`}
                  </p>
                  {preview.summary.missing_categories.length > 0 && (
                    <p>
                      No evaluation data for{" "}
                      {preview.summary.missing_categories.join(", ")}.
                    </p>
                  )}
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={consent}
                      onChange={(e) => setConsent(e.target.checked)}
                    />
                    I can upload these tickets to my private Kaggle dataset.
                  </label>
                  <p className="form-hint">
                    Emails, common phone patterns and known token patterns are
                    masked. Review your file for other sensitive content first.
                  </p>
                  <button
                    className="button primary"
                    disabled={
                      busy ||
                      running ||
                      !consent ||
                      !data.connected ||
                      !data.connector_available
                    }
                    onClick={() => void train()}
                  >
                    {busy ? "Working…" : "Train"}
                  </button>
                </div>
              )}
            </section>
          </div>
          <section className="settings-card">
            <div className="settings-card-heading">
              <h2>Models</h2>
              <span
                className={data.active_model ? "connected-tag" : "quiet-tag"}
              >
                {data.active_model ? "Your model active" : "Laya V5 active"}
              </span>
            </div>
            <p>
              Only verified candidates that improve the held-out comparison can
              be enabled. The sample size matters; results are not a production
              guarantee.
            </p>
            {data.active_model && (
              <button
                disabled={busy}
                className="button secondary"
                onClick={() =>
                  void act("training/restore", {}, "Laya V5 restored")
                }
              >
                Restore V5
              </button>
            )}
            {!data.jobs.length && (
              <p className="settings-empty">
                Your training runs will appear here.
              </p>
            )}
            <div className="train-jobs">
              {data.jobs.map((job) => (
                <article className="train-job" key={job.id}>
                  <div className="train-job-heading">
                    <div>
                      <strong>
                        {new Date(job.created * 1000).toLocaleString()}
                      </strong>
                      <p>
                        {job.summary.tickets} tickets ·{" "}
                        {job.summary.trained_fields.join(", ")}
                      </p>
                    </div>
                    <span
                      className={
                        job.status === "ready" ? "connected-tag" : "quiet-tag"
                      }
                    >
                      {job.status === "ready"
                        ? job.evaluation?.recommended
                          ? "Improved"
                          : "V5 retained"
                        : job.status === "failed"
                          ? "Failed"
                          : job.status === "uncertain" ||
                              job.status === "paused"
                            ? "Check needed"
                            : phaseNames[job.phase] || job.status}
                    </span>
                  </div>
                  {job.error && (
                    <p className="form-error" role="alert">
                      {job.error}
                    </p>
                  )}
                  {job.evaluation && (
                    <>
                      <div className="train-results">
                        {job.evaluation.trained_fields.map((field) => (
                          <div key={field}>
                            <span>{field} · macro F1</span>
                            <strong>
                              {percent(
                                job.evaluation!.baseline[field].macro_f1,
                              )}{" "}
                              →{" "}
                              {percent(
                                job.evaluation!.candidate[field].macro_f1,
                              )}
                            </strong>
                            <small>
                              {job.evaluation!.candidate[field].n} held-out
                              decisions
                            </small>
                          </div>
                        ))}
                      </div>
                      <details className="train-details">
                        <summary>Category breakdown</summary>
                        <div className="train-class-table">
                          <div>
                            <strong>Category</strong>
                            <span>Tickets</span>
                            <span>V5 recall</span>
                            <span>New recall</span>
                          </div>
                          {categoryNames.map((name, index) => {
                            const before =
                              job.evaluation!.baseline.category.per_class[
                                String(index)
                              ];
                            const after =
                              job.evaluation!.candidate.category.per_class[
                                String(index)
                              ];
                            return (
                              <div key={name}>
                                <strong>{name}</strong>
                                <span>{after.n}</span>
                                <span>
                                  {after.n ? percent(before.recall) : "—"}
                                </span>
                                <span>
                                  {after.n ? percent(after.recall) : "—"}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </details>
                    </>
                  )}
                  <div className="settings-actions train-job-actions">
                    {job.status === "ready" && (
                      <>
                        <button
                          className="button primary"
                          disabled={
                            busy ||
                            !job.evaluation?.recommended ||
                            data.active_model === job.id
                          }
                          onClick={() =>
                            void act(
                              "training/use",
                              { id: job.id },
                              "Your model is active",
                            )
                          }
                        >
                          {data.active_model === job.id
                            ? "Active"
                            : "Use model"}
                        </button>
                        <a
                          className="button secondary"
                          href={`/api/training/model?id=${job.id}`}
                        >
                          Download
                        </a>
                      </>
                    )}
                    {(job.status === "paused" ||
                      job.status === "uncertain") && (
                      <button
                        className="button secondary"
                        disabled={busy}
                        onClick={() =>
                          void act(
                            "training/check",
                            { id: job.id },
                            "Checking the existing job. No new training submitted.",
                          )
                        }
                      >
                        Check status
                      </button>
                    )}
                    {(job.status === "paused" ||
                      job.status === "uncertain") && (
                      <button
                        className="button secondary"
                        disabled={busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              "Stop the private task on Kaggle first. Ending tracking does not cancel GPU usage or delete remote data. Continue?",
                            )
                          )
                            void act(
                              "training/abandon",
                              { id: job.id, confirm_remote_stopped: true },
                              "Tracking ended. Remote data remains on Kaggle.",
                            );
                        }}
                      >
                        End tracking
                      </button>
                    )}
                    <a
                      className="train-text-link"
                      href={job.kernel_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Kaggle task ↗
                    </a>
                    <a
                      className="train-text-link"
                      href={job.dataset_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Private data ↗
                    </a>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
