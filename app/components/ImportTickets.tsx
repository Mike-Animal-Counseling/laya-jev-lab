"use client";

import { useEffect, useRef, useState } from "react";
import Icon from "./Icon";
import { request } from "../lib/api";
import type { Provider, Ticket } from "../lib/tickets";

type Row = {
  subject: string;
  message: string;
  customer: string;
  company: string;
  channel: string;
};
type Preview = {
  sheet: string;
  rows: { row: number; status: "ready" | "duplicate" | "error"; issue: string; ticket: Partial<Row> }[];
  available: number;
  ready: number;
  duplicates: number;
  errors: number;
};
export type ImportResult = { tickets: Ticket[]; imported: number; skipped: number };

export default function ImportTickets({
  provider, onBusy, onImported, onCancel,
}: {
  provider: Provider;
  onBusy: (busy: boolean) => void;
  onImported: (result: ImportResult) => void;
  onCancel: () => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [source, setSource] = useState<"file" | "email" | "zendesk" | "api">("file");
  const [connections, setConnections] = useState({ email: false, zendesk: false, api: false });
  const input = useRef<HTMLInputElement>(null);
  const requestId = useRef("");
  const inFlight = useRef(false);
  useEffect(() => {
    let active = true;
    request<typeof connections>("intake/status", provider).then((data) => { if (active) setConnections(data); }).catch(() => {});
    return () => { active = false; };
  }, [provider]);

  async function selectFile(file?: File) {
    if (!file || inFlight.current) return;
    setError("");
    setPreview(null);
    setFileName(file.name);
    if (!(source === "email" ? /\.eml$/i : /\.(xlsx|csv)$/i).test(file.name) || file.size > 2 * 1024 * 1024 || !file.size) {
      setError(`Choose ${source === "email" ? "an .eml" : "an .xlsx or .csv"} file under 2 MB.`);
      return;
    }
    inFlight.current = true;
    setBusy(true);
    onBusy(true);
    try {
      const data = await request<Preview>("import/preview", provider, file);
      requestId.current = crypto.randomUUID();
      setPreview(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      inFlight.current = false;
      setBusy(false);
      onBusy(false);
    }
  }

  async function syncSource() {
    if (source === "file" || inFlight.current) return;
    inFlight.current = true;
    setBusy(true); onBusy(true); setError(""); setPreview(null); setFileName("");
    try {
      const data = await request<Preview>("intake/preview", provider, { source });
      requestId.current = crypto.randomUUID();
      setPreview(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      inFlight.current = false; setBusy(false); onBusy(false);
    }
  }

  async function importRows() {
    if (!preview || inFlight.current || preview.errors || !preview.ready || preview.ready > preview.available) return;
    inFlight.current = true;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      const result = await request<ImportResult>("import", provider, {
        rows: preview.rows.filter((row) => row.status !== "error").map((row) => row.ticket),
        request_id: requestId.current,
      });
      onImported(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      inFlight.current = false;
      setBusy(false);
      onBusy(false);
    }
  }

  return (
    <div className="import-content">
      <p className="dialog-description">Bring your tickets into one place.</p>
      <div className="intake-tabs" aria-label="Import source">
        {([['file', 'Excel / CSV'], ['email', 'Email'], ['zendesk', 'Zendesk'], ['api', 'API']] as const).map(([key, label]) =>
          <button key={key} className={source === key ? 'active' : ''} aria-pressed={source === key} disabled={busy}
            onClick={() => { setSource(key); setPreview(null); setFileName(""); setError(""); }}>{label}</button>)}
      </div>
      <div className="import-steps" aria-label="Import steps">
        {[source === "zendesk" || source === "api" ? "Sync" : "Upload", "Preview", "Import"].map((label, i) => (
          <span key={label} className={i === (preview ? 1 : 0) ? "current" : ""}><b>{i + 1}</b>{label}</span>
        ))}
      </div>
      <input ref={input} className="sr-only" type="file" accept={source === "email" ? ".eml" : ".xlsx,.csv"} aria-label="Import file" disabled={busy}
        onChange={(event) => {
          void selectFile(event.target.files?.[0]);
          event.target.value = "";
        }} />
      {(source === "file" || source === "email") && <button type="button" className={`import-dropzone ${dragging ? "dragging" : ""}`} disabled={busy}
        onClick={() => input.current?.click()}
        onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); void selectFile(event.dataTransfer.files[0]); }}>
        <span className="import-file-icon"><Icon name={busy ? "refresh" : "upload"} size={25} className={busy ? "spin" : ""} /></span>
        <strong>{busy ? "Working…" : fileName || (source === "email" ? "Drop an email here" : "Drop your spreadsheet here")}</strong>
        <small>{fileName ? "Click to choose another file" : `or click to browse · ${source === "email" ? ".eml" : ".xlsx / .csv"} · up to 2 MB`}</small>
      </button>}
      {source !== "file" && <div className="intake-connection">
        <Icon name={source === "email" ? "mail" : "cloud"} size={23} />
        <div><strong>{source === "email" ? "Mailbox" : source === "zendesk" ? "Zendesk" : "REST API"}</strong>
          <small>{connections[source] ? "Configured · Preview before importing" : "Set up a connection to sync tickets."}</small></div>
        <button className="button secondary" disabled={busy || !connections[source]} onClick={() => void syncSource()}>{busy ? "Loading…" : "Sync"}</button>
      </div>}
      {source === "file" && <div className="import-template">
        <span>Start with our format.</span>
        <a className="text-button" href="/api/import/template" download="tickets-template.xlsx"><Icon name="download" size={14} /> Template</a>
      </div>}
      {!preview && source === "file" && <div className="import-columns"><span>Required</span><code>Subject</code><code>Message</code><small>Optional: Customer, Company, Channel</small></div>}
      {preview && <>
        <div className="import-summary" role="status">
          <span><b>{preview.ready}</b> ready</span><span><b>{preview.duplicates}</b> duplicates</span><span className={preview.errors ? "has-errors" : ""}><b>{preview.errors}</b> errors</span>
        </div>
        <div className="import-preview" tabIndex={0} aria-label="Import preview">
          <table><thead><tr><th>Row</th><th>Subject</th><th>Customer</th><th>Status</th></tr></thead>
            <tbody>{preview.rows.map((row) => <tr key={row.row}>
              <td>{row.row}</td><td><strong>{row.ticket.subject || "—"}</strong>{row.issue && <small>{row.issue}</small>}</td>
              <td>{row.ticket.customer || "—"}</td><td><span className={`import-status ${row.status}`}>{row.status === "ready" ? "Ready" : row.status === "duplicate" ? "Skip" : "Fix"}</span></td>
            </tr>)}</tbody>
          </table>
        </div>
        {preview.errors > 0 && <p className="form-error">Fix the marked rows, then upload again. No tickets have been saved.</p>}
        {preview.ready > preview.available && <p className="form-error">Only {preview.available} slots remain. Reduce the file to fit.</p>}
        {preview.ready === 0 && !preview.errors && <p className="import-info">These tickets are already in your inbox.</p>}
      </>}
      {error && <p className="form-error" role="alert">{error}</p>}
      <p className="import-privacy"><Icon name="chip" size={14} /> Saved locally. Import never calls an AI model.</p>
      <div className="form-actions">
        <button className="button secondary" disabled={busy} onClick={onCancel}>Cancel</button>
        <button className="button primary" disabled={busy || !preview || !!preview.errors || !preview.ready || preview.ready > preview.available} onClick={() => void importRows()}>
          <Icon name="upload" size={16} />{busy ? "Working…" : preview?.ready ? `Import ${preview.ready} ticket${preview.ready === 1 ? "" : "s"}` : "Import tickets"}
        </button>
      </div>
    </div>
  );
}
