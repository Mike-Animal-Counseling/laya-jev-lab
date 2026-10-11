"use client";

import { useState } from "react";
import Link from "next/link";

export default function Join() {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [joined, setJoined] = useState<{ workspace: string; username: string } | null>(null);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError("");
    if (password !== confirm) { setError("Passwords do not match."); return; }
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) { setError("Open the invitation link from your workspace owner."); return; }
    setBusy(true);
    try {
      const response = await fetch("/api/auth/join", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, password }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Invitation expired.");
      window.history.replaceState(null, "", "/join");
      setPassword(""); setConfirm(""); setJoined(data);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <main className="auth-shell"><section className="auth-card">
    <div className="auth-brand">model<span>lab.</span></div><h1>{joined ? "You’re in" : "Join workspace"}</h1>
    {joined ? <><p>Workspace: <strong>{joined.workspace}</strong><br />Username: <strong>{joined.username}</strong></p><Link className="button primary full-width" href="/laya-ft">Sign in</Link></> : <>
      <p className="form-hint">Choose a password for your invited account.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <form onSubmit={(e) => void submit(e)}>
        <label>Password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <label>Repeat password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>
        <button className="button primary full-width" disabled={busy}>{busy ? "Joining…" : "Join"}</button>
      </form>
    </>}
  </section></main>;
}
