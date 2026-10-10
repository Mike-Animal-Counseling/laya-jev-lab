"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import Icon from "../components/Icon";
import { request } from "../lib/api";
import type { Ticket } from "../lib/tickets";

export default function SubmitTicket() {
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [customer, setCustomer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ticketId, setTicketId] = useState("");
  const attempt = useRef({ input: "", key: "" });
  const inFlight = useRef(false);

  async function submit() {
    if (inFlight.current) return;
    const input = JSON.stringify([subject.trim(), message.trim(), customer.trim()]);
    if (attempt.current.input !== input) attempt.current = { input, key: crypto.randomUUID() };
    inFlight.current = true; setBusy(true); setError("");
    try {
      const data = await request<{ ticket: Ticket }>("intake/form", "laya-ft", {
        subject: subject.trim(), message: message.trim(), customer: customer.trim() || "Form customer",
        company: "Submitted requests", request_id: attempt.current.key,
      });
      setTicketId(data.ticket.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      inFlight.current = false; setBusy(false);
    }
  }

  return <main className="submit-page">
    <header><Link href="/laya-ft" className="submit-brand">modellab<span>.</span></Link><Link href="/laya-ft">Inbox <Icon name="arrow" size={14} /></Link></header>
    <section className="submit-card">
      <span className="eyebrow">WE’RE HERE TO HELP</span>
      {ticketId ? <div className="submit-success" role="status">
        <span><Icon name="check" size={28} /></span><h1>Request received.</h1><p>Your ticket is <strong>{ticketId}</strong>.</p>
        <Link className="button primary" href={`/laya-ft?ticket=${encodeURIComponent(ticketId)}`}>View ticket <Icon name="arrow" size={15} /></Link>
        <button className="text-button" onClick={() => { setTicketId(""); setSubject(""); setMessage(""); setCustomer(""); attempt.current = { input: "", key: "" }; }}>Submit another</button>
      </div> : <form onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <h1>How can we help?</h1><p>Send a request to the support inbox.</p>
        <label htmlFor="form-customer">Name <small>Optional</small></label>
        <input id="form-customer" maxLength={100} placeholder="Your name" value={customer} disabled={busy} onChange={(e) => setCustomer(e.target.value)} />
        <label htmlFor="form-subject">Subject</label>
        <input id="form-subject" required maxLength={120} placeholder="A short summary" value={subject} disabled={busy} onChange={(e) => setSubject(e.target.value)} />
        <label htmlFor="form-message">Message</label>
        <textarea id="form-message" required maxLength={3000} rows={7} placeholder="Tell us what happened…" value={message} disabled={busy} onChange={(e) => setMessage(e.target.value)} />
        <div className="field-hint"><span>Any language</span><span>{message.length} / 3000</span></div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="button primary full-width" disabled={busy || !subject.trim() || !message.trim()}>{busy ? "Sending…" : "Send request"}<Icon name="arrow" size={15} /></button>
      </form>}
      <p className="submit-note">Local workspace · Requests are saved here.</p>
    </section>
  </main>;
}
