"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Icon from "./components/Icon";
import ModelMark from "./components/ModelMark";
import ModelComparison from "./components/ModelComparison";
import {
  names,
  teams,
  labels,
  priorities,
  pct,
  project,
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
      <strong>{value >= 0.5 ? "有" : "无"}</strong>
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
    message: "正在连接",
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
  const [modal, setModal] = useState<"new" | "rules" | "reset" | null>(null);
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [promptText, setPromptText] = useState("正在加载…");
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
          setError("无法连接工单服务，请确认本地后端已启动，再刷新重试。");
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
          if (active) setHealth({ status: "error", message: "服务未连接" });
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
    (p === provider ? health : { status: "loading", message: "等待连接" });
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
    (t) => t.analysis?.needs_review && t.status !== "assigned",
  ).length;
  const assignedCount = tickets.filter((t) => t.status === "assigned").length;
  const pending = tickets.filter(
    (t) => t.status !== "assigned" && (!t.analysis || isStale(t)),
  );
  const filtered = tickets.filter(
    (t) =>
      (view === "all" ||
        (view === "review" &&
          t.analysis?.needs_review &&
          t.status !== "assigned") ||
        (view === "assigned" && t.status === "assigned")) &&
      (filter === "all" ||
        (filter === "pending"
          ? t.status !== "assigned" && (!t.analysis || isStale(t))
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
      ? "需要关注"
      : view === "assigned"
        ? "已分配工单"
        : "工单收件箱";
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
    setNotice(`本次完成 ${done} / ${queue.length} 条分析`);
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
      setNotice("已记录团队分配");
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
      setNotice("工单已创建，可以开始分析");
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
      setNotice("已重新打开，可以复核或重新分析");
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
      setNotice("工单已导出，请妥善保管客户信息");
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
      setNotice("演示工单已恢复");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function openRules() {
    setModal("rules");
    setPromptText("正在加载…");
    try {
      const d = await api("rubric", provider);
      setPromptText(JSON.stringify(d.questions, null, 2));
    } catch (e) {
      setPromptText((e as Error).message);
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到工单内容
      </a>
      <aside className="navigation">
        <Link
          href="/laya-ft"
          onClick={(e) => {
            if (locked) e.preventDefault();
          }}
          aria-disabled={locked}
          className="wordmark"
          aria-label="Model Lab 首页"
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
            <strong>客服工作空间</strong>
            <small>SUPPORT WORKSPACE</small>
          </div>
          <span className="workspace-dot" />
        </div>
        <div className="nav-caption">工作台</div>
        <nav aria-label="工单队列">
          {(
            [
              {
                key: "all",
                label: "收件箱",
                icon: "inbox",
                count: tickets.length,
              },
              {
                key: "review",
                label: "需要关注",
                icon: "flag",
                count: reviewCount,
              },
              {
                key: "assigned",
                label: "已分配",
                icon: "check",
                count: assignedCount,
              },
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
          aria-label="分类规则"
          className="nav-tool"
          onClick={() => void openRules()}
        >
          <Icon name="settings" size={19} />
          <span>分类规则</span>
          <Icon name="chevron" size={13} />
        </button>
        <div className="nav-bottom">
          <div className="local-model-note">
            <Icon name="chip" size={23} />
            <strong>让模型成为你的助手</strong>
            <p>
              理解工单，提供建议。
              <br />
              由你确认最终分配。
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
            恢复演示工单
          </button>
          <div className="workspace-footer">
            <span className="profile-avatar">ML</span>
            <div>
              <strong>Model Lab</strong>
              <small>工单分析实验室</small>
            </div>
            <span className="workspace-dot" />
          </div>
        </div>
      </aside>

      <main className="main-area" id="main-content">
        <header className="page-header">
          <div>
            <div className="breadcrumb">
              工作台 <Icon name="chevron" size={10} /> 工单管理
            </div>
            <div className="page-title-line">
              <h1>{viewName}</h1>
              <span className="count-tag">
                {view === "review"
                  ? reviewCount
                  : view === "assigned"
                    ? assignedCount
                    : tickets.length}
              </span>
            </div>
            <p className="page-description">
              合成演示工单 · Laya 本地分析，Jev 使用你自己的 API Key。
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
                  ? "Jev API 已配置"
                  : `${names[provider]} 已就绪`
                : modelHealth(provider).status === "loading"
                  ? "模型连接中"
                  : "模型未就绪"}
            </span>
            <button
              className="button primary"
              disabled={locked}
              onClick={() => {
                setError("");
                setModal("new");
              }}
            >
              <Icon name="plus" size={18} />
              新建工单
            </button>
          </div>
        </header>
        <div className="workspace-toolbar">
          <div className="provider-switch" aria-label="选择分析模型">
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
                  {p === "jev" ? "API" : "本地 V5"}
                </small>
              </Link>
            ))}
          </div>
          <div className="queue-summary">
            <button
              className="icon-button"
              title="导出工单备份"
              aria-label="导出工单备份"
              disabled={locked}
              onClick={() => void exportTickets()}
            >
              <Icon name="document" size={17} />
            </button>
            <span>
              <i className="queue-dot pending" />
              {pending.length} 待分析
            </span>
            <span>
              <i className="queue-dot analyzed" />
              {tickets.filter((t) => t.analysis && !isStale(t)).length} 已分析
            </span>
            <button
              className="icon-button"
              title="刷新工单"
              aria-label="刷新工单"
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
              重试
            </button>
            <button
              className="icon-button"
              aria-label="关闭错误提示"
              onClick={() => setError("")}
            >
              <Icon name="close" size={15} />
            </button>
          </div>
        )}
        <div className={`mailbox ${mobileDetail ? "mobile-detail" : ""}`}>
          <section className="inbox" aria-label="工单列表">
            <div className="list-controls">
              <div className="search">
                <Icon name="search" size={17} />
                <input
                  ref={searchRef}
                  aria-label="搜索工单"
                  placeholder="搜索工单…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                {search ? (
                  <button aria-label="清除搜索" onClick={() => setSearch("")}>
                    <Icon name="close" size={14} />
                  </button>
                ) : (
                  <kbd>Ctrl K</kbd>
                )}
              </div>
              <div className="filters" aria-label="工单状态筛选">
                {[
                  { key: "all", label: "全部" },
                  { key: "pending", label: "待分析" },
                  { key: "analyzed", label: "已分析" },
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
                <div className="list-loading" aria-label="正在加载工单">
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
                        {t.customer?.slice(0, 1) || "客"}
                      </span>
                      <span className="ticket-sender">
                        {t.customer || "客户"}
                      </span>
                      <time>{t.time}</time>
                    </div>
                    <h3>{t.subject}</h3>
                    <p>{t.message}</p>
                    <div className="ticket-row-bottom">
                      <span className="ticket-number">{t.id}</span>
                      <span
                        className={`ticket-status ${t.status === "assigned" ? "assigned" : t.analysis?.needs_review ? "review" : t.analysis && !isStale(t) ? "analyzed" : "pending"}`}
                      >
                        <i />
                        {t.status === "assigned"
                          ? "已分配"
                          : isStale(t)
                            ? "待更新"
                            : t.analysis?.needs_review
                              ? "需复核"
                              : t.analysis
                                ? "已分析"
                                : "待分析"}
                      </span>
                    </div>
                  </button>
                ))
              ) : (
                <div className="empty-list">
                  <Icon name="search" size={30} />
                  <strong>
                    {search ? "没有匹配的工单" : "当前队列暂无工单"}
                  </strong>
                  <p>
                    {search
                      ? "试试客户姓名、关键词或工单编号"
                      : "新建工单，开始一次分析"}
                  </p>
                  {search && (
                    <button
                      className="text-button"
                      onClick={() => setSearch("")}
                    >
                      清除搜索
                    </button>
                  )}
                </div>
              )}
            </div>
            <div className="list-bottom">
              {batch ? (
                <>
                  <div className="batch-progress">
                    <span>正在逐条分析</span>
                    <b>
                      {progress.done} / {progress.total}
                    </b>
                  </div>
                  <button
                    className="batch-button"
                    onClick={() => {
                      stop.current = true;
                      setNotice("将在当前工单完成后停止");
                    }}
                  >
                    <Icon name="stop" size={16} />
                    完成当前后停止
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
                    分析待处理工单
                    <span className="batch-count">{pending.length}</span>
                  </button>
                  <small>
                    {provider === "jev"
                      ? "批量分析将调用 API，产生费用"
                      : "本地推理 · 无需 API 调用"}
                  </small>
                </>
              )}
            </div>
          </section>

          <section
            ref={detailRef}
            className="ticket-workspace"
            aria-label="工单详情"
          >
            <div className="document-toolbar">
              <button
                className="icon-button mobile-back"
                aria-label="返回工单列表"
                onClick={() => setMobileDetail(false)}
              >
                <Icon name="back" size={18} />
              </button>
              <div className="detail-tabs">
                {[
                  { key: "ticket", icon: "document", label: "工单详情" },
                  { key: "compare", icon: "compare", label: "模型对照" },
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
              <div className="ticket-pagination">
                <span>
                  {index + 1} / {filtered.length}
                </span>
                <button
                  className="icon-button"
                  aria-label="上一条工单"
                  disabled={index <= 0}
                  onClick={() => chooseTicket(filtered[index - 1].id)}
                >
                  <Icon name="chevron" size={14} className="rotate" />
                </button>
                <button
                  className="icon-button"
                  aria-label="下一条工单"
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
                <h2>{loading ? "正在载入工作空间" : "让每一条反馈找到归属"}</h2>
                <p>
                  {loading
                    ? "正在获取工单与模型状态…"
                    : "选择或新建一张工单，查看内容与模型建议。"}
                </p>
                {!loading && (
                  <button
                    className="button primary"
                    disabled={locked}
                    onClick={() => setModal("new")}
                  >
                    <Icon name="plus" size={17} />
                    新建工单
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
                      {ticket.channel || "客户反馈"}
                    </span>
                    <span className={`ticket-status ${ticket.status}`}>
                      {ticket.status === "assigned" ? "已分配" : "处理中"}
                    </span>
                  </div>
                  <h2 className="subject">{ticket.subject}</h2>
                  <div className="customer">
                    <span className="avatar large">
                      {ticket.customer?.slice(0, 1) || "客"}
                    </span>
                    <div>
                      <strong>{ticket.customer || "客户"}</strong>
                      <span>{ticket.company || "客户工单"}</span>
                    </div>
                    <time>{ticket.time}</time>
                  </div>
                  <div className="message-heading">
                    <span>客户来信</span>
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
                        ? "收起来信"
                        : "展开完整来信"}
                      <Icon name="chevron" size={14} />
                    </button>
                  )}
                  <div className="reading-note">
                    <Icon name="document" size={15} />
                    <span>原始工单内容 · 模型基于标题与正文分析</span>
                  </div>
                  <details
                    key={`history-${ticket.id}`}
                    className="history-section"
                  >
                    <summary className="section-heading">
                      <span>
                        处理动态 <small>{ticket.history.length} 条记录</small>
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
                            <span>等待开始分析</span>
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
                      智能分析
                    </h3>
                    <span className="model-badge">
                      <i />
                      {names[provider]}
                    </span>
                  </div>
                  {busy?.id === ticket.id && (
                    <div className="processing-note" role="status">
                      <Icon name="refresh" size={16} className="spin" />
                      {names[busy.provider]} 正在理解工单…
                    </div>
                  )}
                  {analysis ? (
                    <>
                      <section className="suggestion">
                        <div className="eyebrow">
                          {ticket.status === "assigned"
                            ? "已确认分配"
                            : "建议负责团队"}
                        </div>
                        <div className="suggestion-heading">
                          <h2>{ticket.team || analysis.suggested_team}</h2>
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
                        <div className="decision-summary" aria-label="关键判断">
                          <span
                            className={`decision-priority ${analysis.priority}`}
                          >
                            {analysis.priority} ·{" "}
                            {priorities[analysis.priority]}
                          </span>
                          {analysis.complaint >= 0.5 && <span>投诉倾向</span>}
                          {analysis.churn >= 0.5 && <span>流失风险</span>}
                          {analysis.refund >= 0.5 && <span>退款诉求</span>}
                        </div>
                        <div className="confidence-row">
                          <span>分类置信度</span>
                          <strong>{pct(analysis.confidence)}</strong>
                        </div>
                        <div className="confidence-track">
                          <i style={{ width: pct(analysis.confidence) }} />
                        </div>
                        {stale && (
                          <p className="confidence-note">
                            模型或规则已更新，请重新分析。
                          </p>
                        )}
                        {!stale && analysis.confidence < 0.65 && (
                          <p className="confidence-note">
                            置信度较低，请人工选择团队。
                          </p>
                        )}
                        {!stale && analysis.churn >= 0.5 && (
                          <p className="confidence-note">
                            存在流失风险，建议优先跟进客户。
                          </p>
                        )}
                        {ticket.status !== "assigned" && (
                          <div className="assignment">
                            <label className="sr-only" htmlFor="team-choice">
                              分配团队
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
                                  ? "请选择负责团队"
                                  : `建议：${analysis.suggested_team}`}
                              </option>
                              {teams.map((team) => (
                                <option key={team}>{team}</option>
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
                              {saving ? "正在分配…" : "确认分配"}
                            </button>
                          </div>
                        )}
                        {ticket.status === "assigned" && (
                          <button
                            className="button secondary full-width reopen-button"
                            disabled={locked}
                            onClick={() => void reopen()}
                          >
                            <Icon name="refresh" size={14} />
                            重新打开工单
                          </button>
                        )}
                      </section>
                      <details
                        key={`analysis-${ticket.id}-${provider}`}
                        className="analysis-details"
                      >
                        <summary>
                          <div>
                            <strong>查看详细判断</strong>
                            <small>五项判断分数、分类分布与模型信息</small>
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
                            <small>紧急程度</small>
                            <strong>
                              {priorities[analysis.priority] ||
                                analysis.priority}
                            </strong>
                          </div>
                          <b>{analysis.priority}</b>
                        </section>
                        <section className="signals">
                          <div className="section-heading">
                            <h3>客户意图</h3>
                            <span>模型分数</span>
                          </div>
                          <Signal label="投诉倾向" value={analysis.complaint} />
                          <Signal label="流失风险" value={analysis.churn} />
                          <Signal label="退款诉求" value={analysis.refund} />
                        </section>
                        <details className="disclosure">
                          <summary>
                            分类分布与模型信息
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
                              模型：{analysis.model}
                              <br />
                              用时：{(analysis.elapsed_ms / 1000).toFixed(1)} s
                              · 输入 {analysis.input_tokens} tokens
                            </p>
                          </div>
                        </details>
                      </details>
                      {ticket.status !== "assigned" && (
                        <button
                          className="reanalyze"
                          disabled={
                            locked || modelHealth(provider).status !== "ready"
                          }
                          onClick={() => void analyze(ticket.id)}
                        >
                          <Icon name="refresh" size={14} />
                          重新分析
                        </button>
                      )}
                    </>
                  ) : (
                    <section className="analysis-empty">
                      <div className="analysis-empty-art">
                        <Icon name="sparkles" size={32} />
                      </div>
                      <h3>从理解这张工单开始</h3>
                      <p>
                        识别负责团队、紧急程度
                        <br />
                        以及投诉、流失和退款诉求。
                      </p>
                      <button
                        className="button primary full-width"
                        disabled={
                          locked || modelHealth(provider).status !== "ready"
                        }
                        onClick={() => void analyze(ticket.id)}
                      >
                        <Icon name="sparkles" size={17} />
                        {busy?.id === ticket.id
                          ? "分析中…"
                          : `使用 ${names[provider]} 分析`}
                      </button>
                      <small>
                        {provider === "jev"
                          ? "发送工单内容至 API · 按调用计费"
                          : "本地运行 · 无 API 调用费用"}
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
                      <strong>看看另一个模型怎么判断</strong>
                      <small>Laya × Jev · 五项结果对照</small>
                    </span>
                    <Icon name="chevron" size={14} />
                  </button>
                  <p className="analysis-footer">
                    <Icon name="user" size={13} />
                    模型提供建议，最终由你确认。
                    <br />
                    分数表示模型判断，不等于准确率。
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
        className={`dialog ${modal === "rules" ? "rules-dialog" : ""}`}
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
                  ? "创建一张新工单"
                  : modal === "rules"
                    ? "透明、一致的判断规则"
                    : "恢复演示工单？"}
              </h2>
            </div>
            <button
              className="icon-button"
              aria-label="关闭弹窗"
              disabled={saving}
              onClick={() => setModal(null)}
            >
              <Icon name="close" />
            </button>
          </header>
          {modal === "new" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <p className="dialog-description">
                粘贴客户的原始反馈，交给模型分析。
              </p>
              <label htmlFor="ticket-subject">
                工单标题 <span>必填</span>
              </label>
              <input
                id="ticket-subject"
                ref={titleRef}
                required
                maxLength={120}
                placeholder="例如：订阅被重复扣款，需要退款"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                disabled={saving}
              />
              <label htmlFor="ticket-message">
                客户反馈 <span>必填</span>
              </label>
              <textarea
                id="ticket-message"
                required
                maxLength={3000}
                rows={7}
                placeholder="输入完整的客户来信，保留问题与诉求…"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                disabled={saving}
              />
              <div className="field-hint">
                <span>支持中文、英文及其他语言输入</span>
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
                  取消
                </button>
                <button
                  className="button primary"
                  disabled={saving || !subject.trim() || !message.trim()}
                >
                  <Icon name="plus" size={17} />
                  {saving ? "创建中…" : "创建工单"}
                </button>
              </div>
            </form>
          )}
          {modal === "rules" && (
            <div className="rules-content">
              <p className="dialog-description">
                两个模型使用相同的五项判断任务。分类置信度低于 65%
                时，需要人工确认团队。
              </p>
              <div className="team-responsibilities">
                {[
                  "退款、重复扣费、发票与支付争议",
                  "功能故障、服务中断、导出与集成问题",
                  "价格、购买、试用、演示与套餐咨询",
                  "登录、密码、账号找回与换绑",
                  "功能建议、一般反馈及其他请求",
                ].map((text, i) => (
                  <div key={text}>
                    <span className="team-index">0{i + 1}</span>
                    <strong>{teams[i]}</strong>
                    <p>{text}</p>
                  </div>
                ))}
              </div>
              <p className="dialog-description">
                投诉、流失、退款分数达到 50% 时判定为“有”；紧急度分数 ≥ 1.7 为
                P1，≥ 0.9 为 P2，其余为 P3。分配仅记录在此工作空间。
              </p>
              <details className="prompt-source">
                <summary>查看当前模型判断问题</summary>
                <pre>{promptText}</pre>
              </details>
            </div>
          )}
          {modal === "reset" && (
            <>
              <p className="dialog-description">
                这会清除新建工单，以及所有模型的分析和分配记录，并恢复初始演示数据。恢复前会自动保留最近一次数据库备份。
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
                  保留当前工单
                </button>
                <button
                  className="button danger"
                  disabled={saving}
                  onClick={() => void reset()}
                >
                  {saving ? "正在恢复…" : "确认恢复演示数据"}
                </button>
              </div>
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}
