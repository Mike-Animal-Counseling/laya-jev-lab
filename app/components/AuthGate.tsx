"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AuthContext, type Auth } from "../lib/auth";
import { clearSession, request } from "../lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [auth, setAuth] = useState<Auth | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [workspace, setWorkspace] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    let active = true;
    const expire = () => { clearSession(); setAuth((old) => old?.mode === "cloud" ? { mode: "cloud", authenticated: false, user: null } : old); };
    window.addEventListener("session-expired", expire);
    fetch("/api/auth/status", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Service unavailable. Start the backend and refresh.");
        const value = (await response.json()) as Auth;
        if (value.mode !== "local" && value.mode !== "cloud") throw new Error("Invalid service response.");
        if (active) setAuth(value);
      })
      .catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; window.removeEventListener("session-expired", expire); };
  }, []);

  async function login(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspace, username, password }) });
      const value = (await response.json()) as { error?: string };
      if (!response.ok) throw new Error(value.error || "Sign in failed.");
      clearSession(); setPassword(""); window.location.assign("/laya-ft");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function logout() {
    setBusy(true);
    try {
      await request("auth/logout", "laya-ft", {});
      clearSession(); window.location.assign("/laya-ft");
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }

  if (auth?.mode === "local" || path === "/join") return <AuthContext.Provider value={auth || { mode: "cloud", authenticated: false, user: null }}>{children}</AuthContext.Provider>;
  if (auth?.authenticated) return <AuthContext.Provider value={auth}>
    <div className="account-bar">
      <span><strong>{auth.user?.name}</strong><span className="account-separator">/</span>{auth.user?.username}<small>{auth.user?.role}</small></span>
      <nav>{auth.user?.role === "owner" && <Link href="/settings">Settings</Link>}<button disabled={busy} onClick={() => void logout()}>Sign out</button></nav>
    </div>
    {error && <p className="account-error" role="alert">{error}</p>}
    {children}
  </AuthContext.Provider>;
  return <main className="auth-shell"><section className="auth-card">
    <div className="auth-brand">model<span>lab.</span></div>
    <p className="eyebrow">Ticket workspace</p><h1>Sign in</h1>
    {!auth && !error ? <p>Connecting…</p> : <>
      {error && <p className="form-error" role="alert">{error}</p>}
      {!auth && <button className="button secondary" onClick={() => window.location.reload()}>Reconnect</button>}
      <form onSubmit={(e) => void login(e)}>
        <label>Workspace<input required autoComplete="organization" value={workspace} onChange={(e) => setWorkspace(e.target.value.toLowerCase())} maxLength={32} placeholder="your-team" /></label>
        <label>Username<input required autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value.toLowerCase())} maxLength={32} /></label>
        <label>Password<input required type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} maxLength={128} /></label>
        <button className="button primary full-width" disabled={busy || !auth}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="form-hint">Use the workspace and account created by your operator.</p>
    </>}
  </section></main>;
}
