"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { request } from "../lib/api";
import { useAuth } from "../lib/auth";

type Settings = {
  connections: { zendesk: boolean; api: boolean; email: boolean };
  zendesk: { subdomain: string; client_id: string; has_client_secret: boolean };
  jev_configured: boolean;
  sync: { enabled: boolean; interval: number; running: boolean; failures: number; last_run: { at?: number; status?: string; code?: string; imported?: number; updated?: number; caught_up?: boolean } };
  members: { id: string; username: string; role: string; enabled: number }[];
  api_keys: { id: string; name: string; scopes: string[]; expires: number }[];
};
type Tab = "Connections" | "Sync" | "Team" | "API";

export default function SettingsPage() {
  const auth = useAuth();
  const [data, setData] = useState<Settings | null>(null);
  const [tab, setTab] = useState<Tab>("Connections");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [domain, setDomain] = useState("");
  const [client, setClient] = useState("");
  const [secret, setSecret] = useState("");
  const [jevKey, setJevKey] = useState("");
  const [sources, setSources] = useState<Record<string, string>>({});
  const [enabled, setEnabled] = useState(false);
  const [interval, setIntervalValue] = useState(600);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState("member");
  const [invite, setInvite] = useState("");
  const [keyName, setKeyName] = useState("");
  const [scopes, setScopes] = useState(["classify"]);
  const [newKey, setNewKey] = useState("");
  const owner = auth.mode === "cloud" && auth.user?.role === "owner";

  async function load() {
    const value = await request<Settings>("settings", "laya-ft");
    setData(value); return value;
  }
  useEffect(() => {
    if (!owner) return;
    let active = true;
    request<Settings>("settings", "laya-ft")
      .then((value) => { if (active) { setData(value); setDomain(value.zendesk.subdomain); setClient(value.zendesk.client_id); setEnabled(value.sync.enabled); setIntervalValue(value.sync.interval); } })
      .catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [owner]);

  async function act<T>(path: string, body: object, success: string): Promise<T | null> {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await request<T>(path, "laya-ft", body);
      await load(); setNotice(success); return result;
    } catch (e) { setError((e as Error).message); return null; }
    finally { setBusy(false); }
  }
  async function saveZendesk(event: React.FormEvent) {
    event.preventDefault();
    const result = await act("settings/zendesk", { subdomain: domain, client_id: client, client_secret: secret }, "Zendesk settings saved");
    if (result) setSecret("");
  }
  async function connect() {
    const value = await act<{ url: string }>("oauth/zendesk/start", {}, "Opening Zendesk");
    if (value) window.location.assign(value.url);
  }
  function sourceField(key: string, label: string, type = "text") {
    return <label key={key}>{label}<input type={type} autoComplete={type === "password" ? "new-password" : "off"} maxLength={4096} value={sources[key] || ""} onChange={(e) => setSources((old) => ({ ...old, [key]: e.target.value }))} /></label>;
  }
  async function saveSources(event: React.FormEvent) {
    event.preventDefault();
    const values = Object.fromEntries(Object.entries(sources).filter(([, value]) => value));
    if (await act("settings/connections", { values }, "Source settings saved")) setSources({});
  }
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setNotice("Copied"); }
    catch { setNotice("Select and copy the value."); }
  }

  return <main className="settings-shell">
    <header className="settings-heading"><div><Link href="/laya-ft" className="settings-back">← Inbox</Link><p className="eyebrow">Workspace</p><h1>Settings</h1><p>Connect sources. Keep your team in sync.</p></div></header>
    {!owner ? <p className="settings-empty">Workspace settings are managed by the owner in self-hosted mode.</p> : <>
      <nav className="settings-tabs" aria-label="Settings">{(["Connections", "Sync", "Team", "API"] as Tab[]).map((name) => <button key={name} className={tab === name ? "active" : ""} onClick={() => setTab(name)}>{name}</button>)}</nav>
      {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="settings-notice" role="status">{notice}</p>}
      {!data ? <p>Loading settings…</p> : <>
        {tab === "Connections" && <div className="settings-grid">
          <section className="settings-card"><div className="settings-card-heading"><h2>Zendesk</h2><span className={data.connections.zendesk ? "connected-tag" : "quiet-tag"}>{data.connections.zendesk ? "Connected" : "Not connected"}</span></div>
            <form onSubmit={(e) => void saveZendesk(e)}><label>Subdomain<input required value={domain} maxLength={63} placeholder="your-team" onChange={(e) => setDomain(e.target.value.toLowerCase())} /></label><label>Client ID<input required value={client} maxLength={256} onChange={(e) => setClient(e.target.value)} /></label><label>Client secret <small>Optional for public clients</small><input type="password" autoComplete="new-password" value={secret} maxLength={4096} placeholder={data.zendesk.has_client_secret ? "Saved · leave blank to keep" : ""} onChange={(e) => setSecret(e.target.value)} /></label><button className="button secondary" disabled={busy}>Save</button></form>
            <p className="form-hint">Callback: <code>/api/oauth/zendesk/callback</code><br />Register it under your deployment’s public URL.</p>
            <div className="settings-actions"><button className="button primary" disabled={busy || !data.zendesk.client_id} onClick={() => void connect()}>Connect</button>{data.connections.zendesk && <button className="button secondary" disabled={busy} onClick={() => void act<{ provider_revoked: boolean }>("oauth/zendesk/disconnect", {}, "Disconnected").then((value) => { if (value && !value.provider_revoked) setNotice("Disconnected locally. Revoke the authorization in Zendesk too."); })}>Disconnect</button>}</div>
          </section>
          <section className="settings-card"><div className="settings-card-heading"><h2>Jev</h2><span className={data.jev_configured ? "connected-tag" : "quiet-tag"}>{data.jev_configured ? "Configured" : "Not configured"}</span></div><p>Use your own TypeSafe key. Analysis sends the selected ticket to Jev.</p>
            <form onSubmit={(e) => { e.preventDefault(); void act("settings/jev", { api_key: jevKey }, "Jev configured").then((result) => { if (result) setJevKey(""); }); }}><label>API key<input required type="password" autoComplete="new-password" maxLength={4096} value={jevKey} onChange={(e) => setJevKey(e.target.value)} /></label><div className="settings-actions"><button className="button primary" disabled={busy}>Save key</button>{data.jev_configured && <button type="button" className="button secondary" disabled={busy} onClick={() => void act("settings/jev", { api_key: "" }, "Jev key removed")}>Remove</button>}</div></form>
            <p className="form-hint">Credentials stay encrypted on the server and are never returned here.</p>
          </section>
          <section className="settings-card"><div className="settings-card-heading"><h2>REST API</h2><span className="quiet-tag">{data.connections.api ? "Configured" : "Optional"}</span></div><form onSubmit={(e) => void saveSources(e)}>{sourceField("TICKET_API_URL", "HTTPS endpoint", "url")}{sourceField("TICKET_API_TOKEN", "Bearer token", "password")}<div className="settings-actions"><button className="button secondary" disabled={busy}>Save</button>{data.connections.api && <button type="button" className="button secondary" disabled={busy} onClick={() => void act("settings/connections", { values: { TICKET_API_URL: "", TICKET_API_TOKEN: "" } }, "API disconnected")}>Disconnect</button>}</div></form><p className="form-hint">Manual preview/import. Returns up to 100 tickets.</p></section>
          <section className="settings-card"><div className="settings-card-heading"><h2>Email</h2><span className="quiet-tag">{data.connections.email ? "Configured" : "Optional"}</span></div><form onSubmit={(e) => void saveSources(e)}>{sourceField("MAIL_IMAP_HOST", "IMAP host")}{sourceField("MAIL_IMAP_USER", "Username")}{sourceField("MAIL_IMAP_PASSWORD", "App password", "password")}{sourceField("MAIL_IMAP_FOLDER", "Folder")}<div className="settings-actions"><button className="button secondary" disabled={busy}>Save</button>{data.connections.email && <button type="button" className="button secondary" disabled={busy} onClick={() => void act("settings/connections", { values: { MAIL_IMAP_HOST: "", MAIL_IMAP_USER: "", MAIL_IMAP_PASSWORD: "" } }, "Mailbox disconnected")}>Disconnect</button>}</div></form><p className="form-hint">Read-only TLS connection. Manual preview/import.</p></section>
        </div>}
        {tab === "Sync" && <section className="settings-card settings-wide"><div className="settings-card-heading"><h2>Zendesk sync</h2><span className="quiet-tag">{data.sync.running ? "Running" : data.sync.enabled ? "Scheduled" : "Paused"}</span></div><p>Import new and updated tickets automatically. Sync does not call either AI model.</p><form onSubmit={(e) => { e.preventDefault(); void act("sync/configure", { enabled, interval }, enabled ? "Auto sync enabled" : "Auto sync paused"); }}><label className="check-label"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Auto sync</label><label>Interval<select value={interval} onChange={(e) => setIntervalValue(Number(e.target.value))}>{[[60, "1 minute"], [300, "5 minutes"], [600, "10 minutes"], [1800, "30 minutes"], [3600, "1 hour"], [86400, "1 day"]].map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label><div className="settings-actions"><button className="button primary" disabled={busy || (!data.connections.zendesk && enabled)}>Save</button><button className="button secondary" type="button" disabled={busy || data.sync.running || !data.connections.zendesk} onClick={() => void act("sync/run", {}, "Page synchronized")}>Sync now</button></div></form><div className="sync-summary"><span>Last run<strong>{data.sync.last_run.at ? new Date(data.sync.last_run.at * 1000).toLocaleString() : "No runs yet"}</strong></span><span>Status<strong>{data.sync.last_run.status || "Ready"}</strong></span><span>Imported / updated<strong>{data.sync.last_run.imported || 0} / {data.sync.last_run.updated || 0}</strong></span></div>{data.sync.last_run.code && <p className="form-error">{data.sync.last_run.code.replaceAll("_", " ")}. The cursor was retained.</p>}<p className="form-hint">Starts one hour before workspace creation. Saves progress across restarts; retries source failures with backoff. Incremental export requires an authorized Zendesk admin.</p></section>}
        {tab === "Team" && <section className="settings-card settings-wide"><h2>Team</h2><form className="invite-form" onSubmit={(e) => { e.preventDefault(); void act<{ url: string }>("members/invite", { username, role }, "Invitation created").then((value) => { if (value) { setInvite(value.url); setUsername(""); } }); }}><label>Username<input required minLength={2} maxLength={32} pattern="[a-z0-9][a-z0-9_.-]+" value={username} onChange={(e) => setUsername(e.target.value.toLowerCase())} /></label><label>Role<select value={role} onChange={(e) => setRole(e.target.value)}><option value="member">Member</option><option value="viewer">Viewer</option></select></label><button className="button primary" disabled={busy}>Invite</button></form>{invite && <div className="one-time-value"><p>Share this link. Valid for 24 hours.</p><input aria-label="Invitation link" readOnly value={invite} onFocus={(e) => e.target.select()} /><button className="text-button" onClick={() => void copy(invite)}>Copy</button></div>}<div className="settings-table">{data.members.map((member) => <div key={member.id}><strong>{member.username}</strong><span>{member.role}</span><span>{member.enabled ? "Active" : "Disabled"}</span>{member.role !== "owner" && !!member.enabled && <button className="text-button" disabled={busy} onClick={() => void act("members/disable", { id: member.id }, "Member disabled")}>Disable</button>}</div>)}</div><p className="form-hint">Members import, analyze and review. Viewers read and export. Owners manage connections, people and keys.</p></section>}
        {tab === "API" && <section className="settings-card settings-wide"><h2>Integration keys</h2><p>Connect an existing helpdesk without using the inbox.</p><form onSubmit={(e) => { e.preventDefault(); void act<{ token: string }>("keys/create", { name: keyName, scopes }, "Integration key created").then((value) => { if (value) { setNewKey(value.token); setKeyName(""); } }); }}><label>Name<input required maxLength={60} value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="Helpdesk integration" /></label><div className="scope-options">{[["classify", "Classify"], ["tickets:read", "Read tickets"], ["tickets:write", "Import / update"]].map(([scope, label]) => <label className="check-label" key={scope}><input type="checkbox" checked={scopes.includes(scope)} onChange={(e) => setScopes((old) => e.target.checked ? [...old, scope] : old.filter((s) => s !== scope))} />{label}</label>)}</div><button className="button primary" disabled={busy || !scopes.length}>Create key</button></form>{newKey && <div className="one-time-value"><p>Save this key now. It expires in 90 days and is shown once.</p><input aria-label="New integration key" readOnly value={newKey} onFocus={(e) => e.target.select()} /><button className="text-button" onClick={() => void copy(newKey)}>Copy</button></div>}<div className="settings-table">{data.api_keys.map((key) => <div key={key.id}><strong>{key.name}</strong><span>{key.scopes.join(", ")}</span><span>{new Date(key.expires * 1000).toLocaleDateString()}</span><button className="text-button" disabled={busy} onClick={() => void act("keys/revoke", { id: key.id }, "Key revoked")}>Revoke</button></div>)}</div><div className="api-endpoints"><code>POST /v1/classify</code><code>POST /v1/compare</code><code>POST /v1/tickets</code><a href="/v1/openapi.json" target="_blank" rel="noreferrer">OpenAPI contract ↗</a></div><p className="form-hint">Keys are scoped to this workspace. Use a UUID Idempotency-Key on writes. Classification stores the result, not the original ticket text.</p></section>}
      </>}
    </>}
  </main>;
}
