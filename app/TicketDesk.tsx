"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Icon from "./components/Icon";
import ModelMark from "./components/ModelMark";
import ModelComparison from "./components/ModelComparison";
import ImportTickets from "./components/ImportTickets";
import {
  names,
  teams,
  labels,
  priorities,
  pct,
  project,
  teamLabel,
  type Provider,
  type Ticket,
  type Health,
  type ApiData,
} from "./lib/tickets";
import { request } from "./lib/api";

const api = (path: string, provider: Provider, body?: object) =>
  request<ApiData>(path, provider, body);

function Signal({ label, value }: { label: string; value: number }) {
  return (
    <div className={`signal ${value >= 0.5 ? "positive" : ""}`}>
      <span>{label}</span>
      <div className="signal-track">
        <i style={{ width: pct(value) }} />
      </div>
      <strong>{value >= 0.5 ? "Yes" : "No"}</strong>
      <small>{pct(value)}</small>
    </div>
  );
}

export default function TicketDesk({
  initialProvider: provider,
}: {
  initialProvider: Provider;
}) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState("");
  const [view, setView] = useState("all");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [health, setHealth] = useState<Health>({
    status: "loading",
    message: "Connecting",
  });
  const [rubricId, setRubricId] = useState("");
  const [busy, setBusy] = useState<{ id: string; provider: Provider } | null>(
    null,
  );
  const [batch, setBatch] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [modal, setModal] = useState<"new" | "rules" | "reset" | "import" | null>(null);
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [teamChoice, setTeamChoice] = useState({ id: "", team: "" });
  const [detailTab, setDetailTab] = useState("ticket");
  const [mobileDetail, setMobileDetail] = useState(false);
  const [expandedMessage, setExpandedMessage] = useState("");
  const detailRef = useRef<HTMLElement>(null);
  const createAttempt = useRef({ key: "", input: "" });
  const stop = useRef(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    stop.current = false;
    api("tickets", provider)
      .then((data) => {
        if (!active) return;
        setTickets(data.tickets);
        setRubricId(data.rubric_id);
        const id = new URLSearchParams(window.location.search).get("ticket");
        setSelected(id || data.tickets[0]?.id || "");
        setMobileDetail(!!id);
      })
      .catch(() => {
        if (active)
          setError("Start the local service, then refresh.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    let timer: ReturnType<typeof setTimeout>;
    const ping = async () => {
      if (!active) return;
      if (!document.hidden) {
        try {
          const data = await api("health", provider);
          if (active) {
            setHealth(data);
            setRubricId(data.rubric_id);
          }
        } catch {
          if (active) setHealth({ status: "error", message: "Offline" });
        }
      }
      if (active) timer = setTimeout(ping, 5000);
    };
    void ping();
    return () => {
      active = false;
      stop.current = true;
      clearTimeout(timer);
    };
  }, [provider]);
  useEffect(() => {
    if (!busy && !batch && !saving && !subject && !message) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy, batch, saving, subject, message]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (modal) {
      if (!dialogRef.current?.open) dialogRef.current?.showModal();
      if (modal === "new") titleRef.current?.focus();
    } else dialogRef.current?.close();
  }, [modal]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k" && !modal) {
        e.preventDefault();
        setMobileDetail(false);
        requestAnimationFrame(() => searchRef.current?.focus());
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [modal]);

  const modelHealth = (p: Provider) =>
    health.providers?.[p] ||
    (p === provider ? health : { status: "loading", message: "Connecting" });
  const isStale = (t: Ticket, p: Provider = provider) => {
    const a = t.runs[p].analysis;
    return (
      !!a &&
      ((!!rubricId && a.rubric_id !== rubricId) ||
        (
          !!modelHealth(p).model &&
          a.model !== modelHealth(p).model))
    );
  };
  const reviewCount = tickets.filter(
    (t) => t.analysis?.needs_review && !["assigned", "done"].includes(t.status),
  ).length;
  const assignedCount = tickets.filter((t) => t.status === "assigned").length;
  const doneCount = tickets.filter((t) => t.status === "done").length;
  const pending = tickets.filter(
    (t) => !["assigned", "done"].includes(t.status) && (!t.analysis || isStale(t)),
  );
  const filtered = tickets.filter(
    (t) =>
      ((view === "all" && t.status !== "done") ||
        (view === "review" &&
          t.analysis?.needs_review &&
          !["assigned", "done"].includes(t.status)) ||
        (view === "assigned" && t.status === "assigned") ||
        (view === "done" && t.status === "done")) &&
      (filter === "all" ||
        (filter === "pending"
          ? !["assigned", "done"].includes(t.status) && (!t.analysis || isStale(t))
          : t.status === filter && !isStale(t))) &&
      `${t.subject} ${t.customer} ${t.id} ${t.message}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const ticket = filtered.find((t) => t.id === selected) || filtered[0];
  const index = ticket ? filtered.indexOf(ticket) : -1;
  const analysis = ticket?.analysis;
  const stale = !!ticket && isStale(ticket);
  const chosenTeam = teamChoice.id === ticket?.id ? teamChoice.team : "";
  const locked = !!busy || batch || saving || refreshing || loading;
  const viewName =
    view === "review"
      ? "Flag"
      : view === "assigned"
        ? "Assigned"
        : view === "done" ? "Done" : "Inbox";
  const update = (next: Ticket) => {
    setTickets((previous) =>
      previous.map((t) => (t.id === next.id ? project(next, provider) : t)),
    );
    setTeamChoice({ id: "", team: "" });
  };
  const chooseTicket = (id: string) => {
    setSelected(id);
    setMobileDetail(true);
    setTeamChoice({ id: "", team: "" });
    const url = new URL(window.location.href);
    url.searchParams.set("ticket", id);
    window.history.replaceState(null, "", url);
    requestAnimationFrame(() => {
      if (
        detailRef.current &&
        detailRef.current.getBoundingClientRect().top < 0
      )
        detailRef.current.scrollIntoView({ block: "start" });
    });
  };
  const changeView = (next: string) => {
    setView(next);
    setFilter("all");
    setSearch("");
    setMobileDetail(false);
  };
  async function refresh() {
    setRefreshing(true);
    setError("");
    try {
      const d = await api("tickets", provider);
      setTickets(d.tickets);
      setRubricId(d.rubric_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }
  async function analyze(
    id: string,
    target: Provider = provider,
    inBatch = false,
  ) {
    if (busy) return false;
    if (!inBatch) chooseTicket(id);
    setBusy({ id, provider: target });
    setError("");
    try {
      const data = await api("analyze", target, { id });
      update(data.ticket);
      if (!inBatch && filter === "pending") setFilter("all");
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(null);
    }
  }
  async function analyzeAll() {
    if (locked) return;
    const queue = [...pending];
    stop.current = false;
    setBatch(true);
    setProgress({ done: 0, total: queue.length });
    let done = 0;
    for (const t of queue) {
      if (stop.current || !(await analyze(t.id, provider, true))) break;
      done++;
      setProgress({ done, total: queue.length });
    }
    setBatch(false);
    setNotice(`Analyzed ${done} of ${queue.length}`);
  }
  async function assign() {
    if (!ticket || !analysis) return;
    setSaving(true);
    setError("");
    try {
      const d = await api("assign", provider, {
        id: ticket.id,
        team: chosenTeam || analysis.suggested_team,
        expected_revision: ticket.revision,
      });
      update(d.ticket);
      setNotice("Assigned");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function create() {
    if (saving) return;
    const input = JSON.stringify([subject.trim(), message.trim()]);
    if (createAttempt.current.input !== input)
      createAttempt.current = { input, key: crypto.randomUUID() };
    setSaving(true);
    setError("");
    try {
      const d = await api("tickets", provider, {
        subject: subject.trim(),
        message: message.trim(),
        request_id: createAttempt.current.key,
      });
      setTickets((old) => [
        d.ticket,
        ...old.filter((t) => t.id !== d.ticket.id),
      ]);
      changeView("all");
      chooseTicket(d.ticket.id);
      setDetailTab("ticket");
      setModal(null);
      setSubject("");
      setMessage("");
      createAttempt.current = { input: "", key: "" };
      setNotice("Ticket created");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function reopen() {
    if (!ticket || locked) return;
    setSaving(true);
    setError("");
    try {
      const d = await api("reopen", provider, {
        id: ticket.id,
        expected_revision: ticket.revision,
      });
      update(d.ticket);
      changeView("all");
      chooseTicket(d.ticket.id);
      setNotice("Ticket reopened");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function exportTickets() {
    setRefreshing(true);
    setError("");
    try {
      const data = await api("export", provider);
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `model-lab-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("Export downloaded");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }
  async function reset() {
    setSaving(true);
    setError("");
    try {
      const d = await api("reset", provider, {});
      setTickets(d.tickets);
      setSelected(d.tickets[0]?.id || "");
      changeView("all");
      setModal(null);
      setNotice("Demo restored");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function resolve() {
    if (!ticket || locked) return;
    setSaving(true);
    setError("");
    try {
      const data = await api("resolve", provider, { id: ticket.id, expected_revision: ticket.revision });
      update(data.ticket);
      setNotice("Ticket marked done");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  function openRules() {
    setModal("rules");
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="navigation">
        <Link
          href="/laya-ft"
          onClick={(e) => {
            if (locked) e.preventDefault();
          }}
          aria-disabled={locked}
          className="wordmark"
          aria-label="Model Lab home"
        >
          <span className="brand-symbol">
            <i />
            <i />
            <i />
          </span>
          model<span className="brand-light">lab</span>
          <span className="wordmark-dot">.</span>
        </Link>
        <div className="workspace-chip">
          <span className="workspace-icon">M</span>
          <div>
            <strong>Support</strong>
            <small>SUPPORT WORKSPACE</small>
          </div>
          <span className="workspace-dot" />
        </div>
        <div className="nav-caption">Workspace</div>
        <nav aria-label="Queues">
          {(
            [
              {
                key: "all",
                label: "Inbox",
                icon: "inbox",
                count: tickets.length - doneCount,
              },
              {
                key: "review",
                label: "Flag",
                icon: "flag",
                count: reviewCount,
              },
              {
                key: "assigned",
                label: "Assigned",
                icon: "user",
                count: assignedCount,
              },
              { key: "done", label: "Done", icon: "check", count: doneCount },
            ] as const
          ).map((item) => (
            <button
              key={item.key}
              aria-label={item.label}
              className={view === item.key ? "active" : ""}
              aria-current={view === item.key ? "page" : undefined}
              onClick={() => changeView(item.key)}
            >
              <Icon name={item.icon} size={19} />
              <span>{item.label}</span>
              <b>{item.count}</b>
            </button>
          ))}
        </nav>
        <div className="nav-divider" />
        <button
          aria-label="Rules"
          className="nav-tool"
          onClick={() => void openRules()}
        >
          <Icon name="settings" size={19} />
          <span>Rules</span>
          <Icon name="chevron" size={13} />
        </button>
        <div className="nav-bottom">
          <div className="local-model-note">
            <Icon name="chip" size={23} />
            <strong>A little help, a clear decision.</strong>
            <p>
              Triage with confidence.
              <br />
              You make the final call.
            </p>
          </div>
          <button
            className="reset-link"
            disabled={locked}
            onClick={() => {
              setError("");
              setModal("reset");
            }}
          >
            <Icon name="refresh" size={14} />
            Reset demo
          </button>
          <div className="workspace-footer">
            <span className="profile-avatar">ML</span>
            <div>
              <strong>Model Lab</strong>
              <small>Ticket workspace</small>
            </div>
            <span className="workspace-dot" />
          </div>
        </div>
      </aside>

      <main className="main-area" id="main-content">
        <header className="page-header">
          <div>
            <div className="breadcrumb">
              Workspace <Icon name="chevron" size={10} /> Tickets
            </div>
            <div className="page-title-line">
              <h1>{viewName}</h1>
              <span className="count-tag">
                {view === "review"
                  ? reviewCount
                  : view === "assigned"
                    ? assignedCount
                    : view === "done" ? doneCount : tickets.length - doneCount}
              </span>
            </div>
            <p className="page-description">
              Less sorting. More supporting.
            </p>
          </div>
          <div className="header-actions">
            <span
              className="connection-status"
              title={modelHealth(provider).message}
            >
              <i className={`status-dot ${modelHealth(provider).status}`} />
              {modelHealth(provider).status === "ready"
                ? provider === "jev"
                  ? "Jev connected"
                  : `${names[provider]} ready`
                : modelHealth(provider).status === "loading"
                  ? "Connecting"
                  : "Not connected"}
            </span>
            <button className="button secondary import-trigger" disabled={locked}
              onClick={() => { setError(""); setModal("import"); }}>
              <Icon name="upload" size={17} /> Import
            </button>
            <button
              className="button primary"
              disabled={locked}
              onClick={() => {
                setError("");
                setModal("new");
              }}
            >
              <Icon name="plus" size={18} />
              New ticket
            </button>
          </div>
        </header>
        <div className="workspace-toolbar">
          <div className="provider-switch" aria-label="Analysis model">
            {(
              [
                "laya-ft",
                "jev",
              ] as Provider[]
            ).map((p) => (
              <Link
                key={p}
                href={`/${p}${ticket ? `?ticket=${encodeURIComponent(ticket.id)}` : ""}`}
                aria-current={provider === p ? "page" : undefined}
                className={`${provider === p ? "active" : ""} ${locked ? "disabled" : ""}`}
                onClick={(e) => {
                  if (locked) e.preventDefault();
                }}
                aria-disabled={locked}
              >
                <ModelMark provider={p} />
                <strong>{names[p]}</strong>
                <small>
                  {p === "jev" ? "API" : "Local · V5"}
                </small>
              </Link>
            ))}
          </div>
          <div className="queue-summary">
            <button
              className="icon-button"
              title="Export"
              aria-label="Export"
              disabled={locked}
              onClick={() => void exportTickets()}
            >
              <Icon name="document" size={17} />
            </button>
            <span>
              <i className="queue-dot pending" />
              {pending.length} Pending
            </span>
            <span>
              <i className="queue-dot analyzed" />
              {tickets.filter((t) => t.analysis && !isStale(t)).length} Analyzed
            </span>
            <button
              className="icon-button"
              title="Refresh"
              aria-label="Refresh"
              disabled={locked}
              onClick={() => void refresh()}
            >
              <Icon
                name="refresh"
                size={17}
                className={refreshing ? "spin" : ""}
              />
            </button>
          </div>
        </div>
        {error && !modal && (
          <div className="error-message" role="alert">
            <Icon name="warning" size={17} />
            <span>{error}</span>
            <button onClick={() => void refresh()} disabled={locked}>
              Retry
            </button>
            <button
              className="icon-button"
              aria-label="Dismiss"
              onClick={() => setError("")}
            >
              <Icon name="close" size={15} />
            </button>
          </div>
        )}
        <div className={`mailbox ${mobileDetail ? "mobile-detail" : ""}`}>
          <section className="inbox" aria-label="Tickets">
            <div className="list-controls">
              <div className="search">
                <Icon name="search" size={17} />
                <input
                  ref={searchRef}
                  aria-label="Search tickets"
                  placeholder="Search tickets…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                {search ? (
                  <button aria-label="Clear search" onClick={() => setSearch("")}>
                    <Icon name="close" size={14} />
                  </button>
                ) : (
                  <kbd>Ctrl K</kbd>
                )}
              </div>
              <div className="filters" aria-label="Status">
                {[
                  { key: "all", label: "All" },
                  { key: "pending", label: "Pending" },
                  { key: "analyzed", label: "Analyzed" },
                ].map((f) => (
                  <button
                    key={f.key}
                    aria-pressed={filter === f.key}
                    className={filter === f.key ? "active" : ""}
                    onClick={() => setFilter(f.key)}
                  >
                    {f.label}
                  </button>
                ))}
                <span>{filtered.length}</span>
              </div>
            </div>
            <div className="ticket-list" aria-busy={loading}>
              {loading ? (
                <div className="list-loading" aria-label="Loading tickets">
                  {[1, 2, 3, 4].map((n) => (
                    <div className="skeleton-ticket" key={n}>
                      <i />
                      <i />
                      <i />
                    </div>
                  ))}
                </div>
              ) : filtered.length ? (
                filtered.map((t, i) => (
                  <button
                    key={t.id}
                    className={`ticket-row ${ticket?.id === t.id ? "selected" : ""}`}
                    aria-current={ticket?.id === t.id ? "true" : undefined}
                    onClick={() => chooseTicket(t.id)}
                  >
                    <div className="ticket-row-top">
                      <span className={`avatar avatar-${i % 4}`}>
                        {t.customer?.slice(0, 1) || "C"}
                      </span>
                      <span className="ticket-sender">
                        {t.customer || "Customer"}
                      </span>
                      <time>{t.time}</time>
                    </div>
                    <h3>{t.subject}</h3>
                    <p>{t.message}</p>
                    <div className="ticket-row-bottom">
                      <span className="ticket-number">{t.id}</span>
                      <span
                        className={`ticket-status ${t.status === "done" ? "done" : t.status === "assigned" ? "assigned" : t.analysis?.needs_review ? "review" : t.analysis && !isStale(t) ? "analyzed" : "pending"}`}
                      >
                        <i />
                        {t.status === "done" ? "Done" : t.status === "assigned"
                          ? "Assigned"
                          : isStale(t)
                            ? "Outdated"
                            : t.analysis?.needs_review
                              ? "Flag"
                              : t.analysis
                                ? "Analyzed"
                                : "Pending"}
                      </span>
                    </div>
                  </button>
                ))
              ) : (
                <div className="empty-list">
                  <Icon name="search" size={30} />
                  <strong>
                    {search ? "No matches" : "All clear"}
                  </strong>
                  <p>
                    {search
                      ? "Try a name, keyword or ticket ID."
                      : "Create or import a ticket to get started."}
                  </p>
                  {search && (
                    <button
                      className="text-button"
                      onClick={() => setSearch("")}
                    >
                      Clear search
                    </button>
                  )}
                </div>
              )}
            </div>
            <div className="list-bottom">
              {batch ? (
                <>
                  <div className="batch-progress">
                    <span>Analyzing</span>
                    <b>
                      {progress.done} / {progress.total}
                    </b>
                  </div>
                  <button
                    className="batch-button"
                    onClick={() => {
                      stop.current = true;
                      setNotice("Stopping after this ticket");
                    }}
                  >
                    <Icon name="stop" size={16} />
                    Stop
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="batch-button"
                    disabled={
                      locked ||
                      !pending.length ||
                      modelHealth(provider).status !== "ready"
                    }
                    onClick={() => void analyzeAll()}
                  >
                    <Icon name="sparkles" size={17} />
                    Analyze all
                    <span className="batch-count">{pending.length}</span>
                  </button>
                  <small>
                    {provider === "jev"
                      ? "Uses your Jev API · Billed per call"
                      : "Runs locally · No API fees"}
                  </small>
                </>
              )}
            </div>
          </section>

          <section
            ref={detailRef}
            className="ticket-workspace"
            aria-label="Ticket"
          >
            <div className="document-toolbar">
              <button
                className="icon-button mobile-back"
                aria-label="Back to inbox"
                onClick={() => setMobileDetail(false)}
              >
                <Icon name="back" size={18} />
              </button>
              <div className="detail-tabs">
                {[
                  { key: "ticket", icon: "document", label: "Ticket" },
                  { key: "compare", icon: "compare", label: "Compare" },
                ].map((item) => (
                  <button
                    key={item.key}
                    className={detailTab === item.key ? "active" : ""}
                    aria-pressed={detailTab === item.key}
                    onClick={() => setDetailTab(item.key)}
                  >
                    <Icon
                      name={item.icon as "document" | "compare"}
                      size={16}
                    />
                    {item.label}
                  </button>
                ))}
              </div>
              {ticket && <button className="button secondary resolve-action" disabled={locked}
                onClick={() => void (ticket.status === "done" ? reopen() : resolve())}>
                <Icon name={ticket.status === "done" ? "refresh" : "check"} size={14} />
                {ticket.status === "done" ? "Reopen" : "Done"}
              </button>}
              <div className="ticket-pagination">
                <span>
                  {index + 1} / {filtered.length}
                </span>
                <button
                  className="icon-button"
                  aria-label="Previous ticket"
                  disabled={index <= 0}
                  onClick={() => chooseTicket(filtered[index - 1].id)}
                >
                  <Icon name="chevron" size={14} className="rotate" />
                </button>
                <button
                  className="icon-button"
                  aria-label="Next ticket"
                  disabled={index < 0 || index >= filtered.length - 1}
                  onClick={() => chooseTicket(filtered[index + 1].id)}
                >
                  <Icon name="chevron" size={14} />
                </button>
              </div>
            </div>
            {!ticket ? (
              <div className="empty-reading">
                <span className="empty-art">
                  <Icon name="inbox" size={35} />
                </span>
                <h2>{loading ? "Loading inbox" : "A place for every request."}</h2>
                <p>
                  {loading
                    ? "Getting your workspace ready…"
                    : "Select a ticket to get started."}
                </p>
                {!loading && (
                  <button
                    className="button primary"
                    disabled={locked}
                    onClick={() => setModal("new")}
                  >
                    <Icon name="plus" size={17} />
                    New ticket
                  </button>
                )}
              </div>
            ) : detailTab === "compare" ? (
              <ModelComparison
                ticket={ticket}
                modelHealth={modelHealth}
                isStale={isStale}
                busy={busy}
                locked={locked}
                onAnalyze={analyze}
              />
            ) : (
              <div className="ticket-canvas workspace-scroll">
                <article className="reading-pane">
                  <div className="reading-meta">
                    <span>{ticket.id}</span>
                    <span>
                      <Icon name="mail" size={13} />
                      {ticket.channel || "Message"}
                    </span>
                    <span className={`ticket-status ${ticket.status}`}>
                      {ticket.status === "done" ? "Done" : ticket.status === "assigned" ? "Assigned" : "Open"}
                    </span>
                  </div>
                  <h2 className="subject">{ticket.subject}</h2>
                  <div className="customer">
                    <span className="avatar large">
                      {ticket.customer?.slice(0, 1) || "C"}
                    </span>
                    <div>
                      <strong>{ticket.customer || "Customer"}</strong>
                      <span>{ticket.company || "Customer"}</span>
                    </div>
                    <time>{ticket.time}</time>
                  </div>
                  <div className="message-heading">
                    <span>Message</span>
                    <span className="message-line" />
                  </div>
                  <div className="customer-message">
                    {expandedMessage === ticket.id ||
                    ticket.message.length <= 360
                      ? ticket.message
                      : `${ticket.message.slice(0, 360)}…`}
                  </div>
                  {ticket.message.length > 360 && (
                    <button
                      className="expand-message"
                      aria-expanded={expandedMessage === ticket.id}
                      onClick={() =>
                        setExpandedMessage(
                          expandedMessage === ticket.id ? "" : ticket.id,
                        )
                      }
                    >
                      {expandedMessage === ticket.id
                        ? "Show less"
                        : "Read more"}
                      <Icon name="chevron" size={14} />
                    </button>
                  )}
                  <div className="reading-note">
                    <Icon name="document" size={15} />
                    <span>Analysis uses the subject and message.</span>
                  </div>
                  <details
                    key={`history-${ticket.id}`}
                    className="history-section"
                  >
                    <summary className="section-heading">
                      <span>
                        Activity <small>{ticket.history.length} events</small>
                      </span>
                      <Icon name="chevron" size={15} />
                    </summary>
                    <ol className="history">
                      {ticket.history.length ? (
                        ticket.history.map((h, i) => (
                          <li key={`${h.label}-${i}`}>
                            <i className="history-dot" />
                            <div>
                              <span>{h.label}</span>
                              <time>{h.time}</time>
                            </div>
                          </li>
                        ))
                      ) : (
                        <li>
                          <i className="history-dot" />
                          <div>
                            <span>Pending</span>
                            <time>{ticket.time}</time>
                          </div>
                        </li>
                      )}
                    </ol>
                  </details>
                </article>
                <aside className="analysis-panel">
                  <div className="analysis-heading">
                    <h3>
                      <Icon name="sparkles" size={17} />
                      Insights
                    </h3>
                    <span className="model-badge">
                      <i />
                      {names[provider]}
                    </span>
                  </div>
                  {busy?.id === ticket.id && (
                    <div className="processing-note" role="status">
                      <Icon name="refresh" size={16} className="spin" />
                      {names[busy.provider]} is analyzing…
                    </div>
                  )}
                  {analysis ? (
                    <>
                      <section className="suggestion">
                        <div className="eyebrow">
                          {ticket.status === "assigned"
                            ? "Assigned to"
                            : "Suggested team"}
                        </div>
                        <div className="suggestion-heading">
                          <h2>{teamLabel(ticket.team || analysis.suggested_team)}</h2>
                          <span className="completion-icon">
                            <Icon
                              name={
                                ticket.status === "assigned" ? "check" : "arrow"
                              }
                              size={20}
                            />
                          </span>
                        </div>
                        <p className="suggestion-context">
                          {labels[analysis.category] || analysis.category_label}
                        </p>
                        <div className="decision-summary" aria-label="Key signals">
                          <span
                            className={`decision-priority ${analysis.priority}`}
                          >
                            {analysis.priority} ·{" "}
                            {priorities[analysis.priority]}
                          </span>
                          {analysis.complaint >= 0.5 && <span>Complaint</span>}
                          {analysis.churn >= 0.5 && <span>Churn risk</span>}
                          {analysis.refund >= 0.5 && <span>Refund</span>}
                        </div>
                        <div className="confidence-row">
                          <span>Confidence</span>
                          <strong>{pct(analysis.confidence)}</strong>
                        </div>
                        <div className="confidence-track">
                          <i style={{ width: pct(analysis.confidence) }} />
                        </div>
                        {stale && (
                          <p className="confidence-note">
                            Outdated result. Analyze again.
                          </p>
                        )}
                        {!stale && analysis.confidence < 0.65 && (
                          <p className="confidence-note">
                            Low confidence. Choose a team.
                          </p>
                        )}
                        {!stale && analysis.churn >= 0.5 && (
                          <p className="confidence-note">
                            At risk of leaving. Follow up soon.
                          </p>
                        )}
                        {!["assigned", "done"].includes(ticket.status) && (
                          <div className="assignment">
                            <label className="sr-only" htmlFor="team-choice">
                              Team
                            </label>
                            <select
                              id="team-choice"
                              value={chosenTeam}
                              disabled={locked || stale}
                              onChange={(e) =>
                                setTeamChoice({
                                  id: ticket.id,
                                  team: e.target.value,
                                })
                              }
                            >
                              <option value="">
                                {analysis.confidence < 0.65
                                  ? "Choose a team"
                                  : `Suggested: ${teamLabel(analysis.suggested_team)}`}
                              </option>
                              {teams.map((team) => (
                                <option key={team} value={team}>{teamLabel(team)}</option>
                              ))}
                            </select>
                            <button
                              className="button primary full-width"
                              disabled={
                                locked ||
                                stale ||
                                (analysis.confidence < 0.65 && !chosenTeam)
                              }
                              onClick={() => void assign()}
                            >
                              <Icon name="check" size={17} />
                              {saving ? "Assigning…" : "Assign"}
                            </button>
                          </div>
                        )}
                        {["assigned", "done"].includes(ticket.status) && (
                          <button
                            className="button secondary full-width reopen-button"
                            disabled={locked}
                            onClick={() => void reopen()}
                          >
                            <Icon name="refresh" size={14} />
                            Reopen
                          </button>
                        )}
                      </section>
                      <details
                        key={`analysis-${ticket.id}-${provider}`}
                        className="analysis-details"
                      >
                        <summary>
                          <div>
                            <strong>Details</strong>
                            <small>Scores and model details</small>
                          </div>
                          <Icon name="chevron" size={16} />
                        </summary>
                        <section
                          className={`priority-card ${analysis.priority}`}
                        >
                          <span className="priority-icon">
                            <Icon name="flag" size={19} />
                          </span>
                          <div>
                            <small>Priority</small>
                            <strong>
                              {priorities[analysis.priority] ||
                                analysis.priority}
                            </strong>
                          </div>
                          <b>{analysis.priority}</b>
                        </section>
                        <section className="signals">
                          <div className="section-heading">
                            <h3>Signals</h3>
                            <span>Scores</span>
                          </div>
                          <Signal label="Complaint" value={analysis.complaint} />
                          <Signal label="Churn risk" value={analysis.churn} />
                          <Signal label="Refund" value={analysis.refund} />
                        </section>
                        <details className="disclosure">
                          <summary>
                            Category scores
                            <Icon name="chevron" size={13} />
                          </summary>
                          <div className="disclosure-body">
                            {Object.entries(analysis.probabilities)
                              .sort((a, b) => b[1] - a[1])
                              .map(([label, value]) => (
                                <div className="category-score" key={label}>
                                  <div>
                                    <span>{labels[label] || label}</span>
                                    <strong>{pct(value)}</strong>
                                  </div>
                                  <div className="distribution-track">
                                    <i style={{ width: pct(value) }} />
                                  </div>
                                </div>
                              ))}
                            <p className="technical-note">
                              Model: {analysis.model}
                              <br />
                              Time: {(analysis.elapsed_ms / 1000).toFixed(1)} s
                              · {analysis.input_tokens} tokens
                            </p>
                          </div>
                        </details>
                      </details>
                      {!["assigned", "done"].includes(ticket.status) && (
                        <button
                          className="reanalyze"
                          disabled={
                            locked || modelHealth(provider).status !== "ready"
                          }
                          onClick={() => void analyze(ticket.id)}
                        >
                          <Icon name="refresh" size={14} />
                          Analyze again
                        </button>
                      )}
                    </>
                  ) : (
                    <section className="analysis-empty">
                      <div className="analysis-empty-art">
                        <Icon name="sparkles" size={32} />
                      </div>
                      <h3>Ready when you are.</h3>
                      <p>
                        Find the right team
                        <br />
                        and spot what needs attention.
                      </p>
                      <button
                        className="button primary full-width"
                        disabled={
                          locked || ticket.status === "done" || modelHealth(provider).status !== "ready"
                        }
                        onClick={() => void analyze(ticket.id)}
                      >
                        <Icon name="sparkles" size={17} />
                        {busy?.id === ticket.id
                          ? "Analyzing…"
                          : `Analyze`}
                      </button>
                      <small>
                        {provider === "jev"
                          ? "Sends this ticket to Jev · API fees apply"
                          : "Private, local inference · No API fees"}
                      </small>
                    </section>
                  )}
                  <button
                    className="compare-link"
                    onClick={() => setDetailTab("compare")}
                  >
                    <span className="compare-link-icon">
                      <Icon name="compare" size={20} />
                    </span>
                    <span>
                      <strong>Compare models</strong>
                      <small>Laya & Jev, side by side</small>
                    </span>
                    <Icon name="chevron" size={14} />
                  </button>
                  <p className="analysis-footer">
                    <Icon name="user" size={13} />
                    Suggestions, with you in control.
                    <br />
                    Confidence is not accuracy.
                  </p>
                </aside>
              </div>
            )}
          </section>
        </div>
      </main>
      {notice && (
        <div className="toast" role="status">
          <Icon name="check" size={18} />
          {notice}
        </div>
      )}
      <dialog
        aria-labelledby="dialog-title"
        ref={dialogRef}
        className={`dialog ${modal === "rules" ? "rules-dialog" : ""} ${modal === "import" ? "import-dialog" : ""}`}
        onCancel={(e) => {
          if (saving) e.preventDefault();
          else setModal(null);
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget && !saving) setModal(null);
        }}
      >
        <div className="dialog-inner">
          <header>
            <div>
              <span className="eyebrow">MODEL LAB</span>
              <h2 id="dialog-title">
                {modal === "new"
                  ? "New ticket"
                  : modal === "import" ? "Import tickets"
                  : modal === "rules"
                    ? "Rules"
                    : "Reset demo?"}
              </h2>
            </div>
            <button
              className="icon-button"
              aria-label="Close dialog"
              disabled={saving}
              onClick={() => setModal(null)}
            >
              <Icon name="close" />
            </button>
          </header>
          {modal === "import" && <ImportTickets provider={provider} onBusy={setSaving} onCancel={() => setModal(null)}
            onImported={(result) => {
              setTickets(result.tickets);
              changeView("all");
              setSelected(result.tickets[0]?.id || "");
              setDetailTab("ticket");
              setModal(null);
              setNotice(`${result.imported} tickets imported${result.skipped ? ` · ${result.skipped} duplicates skipped` : ""}`);
            }} />}
          {modal === "new" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <p className="dialog-description">
                Add a request to your inbox.
              </p>
              <label htmlFor="ticket-subject">
                Subject <span>Required</span>
              </label>
              <input
                id="ticket-subject"
                ref={titleRef}
                required
                maxLength={120}
                placeholder="e.g. Duplicate subscription charge"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                disabled={saving}
              />
              <label htmlFor="ticket-message">
                Message <span>Required</span>
              </label>
              <textarea
                id="ticket-message"
                required
                maxLength={3000}
                rows={7}
                placeholder="What does the customer need?"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                disabled={saving}
              />
              <div className="field-hint">
                <span>Any language</span>
                <span>{message.length} / 3000</span>
              </div>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              <div className="form-actions">
                <button
                  type="button"
                  className="button secondary"
                  disabled={saving}
                  onClick={() => setModal(null)}
                >
                  Cancel
                </button>
                <button
                  className="button primary"
                  disabled={saving || !subject.trim() || !message.trim()}
                >
                  <Icon name="plus" size={17} />
                  {saving ? "Creating…" : "Create ticket"}
                </button>
              </div>
            </form>
          )}
          {modal === "rules" && (
            <div className="rules-content">
              <p className="dialog-description">
                Both models use the same five signals. Choose a team manually when confidence is below 65%.
              </p>
              <div className="team-responsibilities">
                {[
                  "Refunds, invoices and payments",
                  "Bugs, outages and integrations",
                  "Pricing, plans and demos",
                  "Login, passwords and recovery",
                  "Feedback and general requests",
                ].map((text, i) => (
                  <div key={text}>
                    <span className="team-index">0{i + 1}</span>
                    <strong>{teamLabel(teams[i])}</strong>
                    <p>{text}</p>
                  </div>
                ))}
              </div>
              <p className="dialog-description">
                Signals are positive at 50%. Priority: P1 ≥ 1.7, P2 ≥ 0.9, otherwise P3. Assignments stay in this workspace.
              </p>
            </div>
          )}
          {modal === "reset" && (
            <>
              <p className="dialog-description">
                Replace all tickets and results with the demo. A local backup is saved first.
              </p>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              <div className="form-actions">
                <button
                  className="button secondary"
                  disabled={saving}
                  onClick={() => setModal(null)}
                >
                  Cancel
                </button>
                <button
                  className="button danger"
                  disabled={saving}
                  onClick={() => void reset()}
                >
                  {saving ? "Resetting…" : "Reset demo"}
                </button>
              </div>
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}
