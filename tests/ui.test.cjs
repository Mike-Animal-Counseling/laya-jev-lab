// Real React DOM interactions with isolated fixtures; no network or customer data.
const { test, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const ts = require("typescript");
const { JSDOM } = require("jsdom");

const dom = new JSDOM(
  '<!doctype html><html><body><div id="root"></div></body></html>',
  { url: "http://127.0.0.1:5180/laya-ft", pretendToBeVisual: true },
);
for (const key of [
  "window",
  "document",
  "HTMLElement",
  "HTMLInputElement",
  "HTMLTextAreaElement",
  "HTMLSelectElement",
  "HTMLDialogElement",
  "Event",
  "MouseEvent",
  "KeyboardEvent",
])
  global[key] = dom.window[key];
global.requestAnimationFrame = (callback) => setTimeout(callback, 0);
global.IS_REACT_ACT_ENVIRONMENT = true;
HTMLElement.prototype.scrollIntoView = function () {};
HTMLDialogElement.prototype.showModal = function () {
  this.open = true;
};
HTMLDialogElement.prototype.close = function () {
  this.open = false;
};

const React = require("react");
const { createRoot } = require("react-dom/client");
const { act } = React;
const originalLoad = Module._load;
Module._load = function (name, ...args) {
  if (name === "next/link")
    return {
      __esModule: true,
      default: ({ children, ...props }) =>
        React.createElement("a", props, children),
    };
  return originalLoad.call(this, name, ...args);
};
for (const extension of [".tsx", ".ts"]) {
  Module._extensions[extension] = (module, filename) =>
    module._compile(
      ts.transpileModule(fs.readFileSync(filename, "utf8"), {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          jsx: ts.JsxEmit.ReactJSX,
          target: ts.ScriptTarget.ES2022,
          esModuleInterop: true,
        },
        fileName: filename,
      }).outputText,
      filename,
    );
}
const TicketDesk = require("../app/TicketDesk.tsx").default;
let root, tickets, calls, failRead;
const clone = (value) => structuredClone(value);
function analysis(provider) {
  return {
    category: "refund",
    category_label: "退款 / 账单",
    priority: "P1",
    urgency: 2,
    complaint: provider === "jev" ? 0.9 : 0.1,
    churn: 0.9,
    refund: 0.99,
    confidence: 0.99,
    probabilities: {
      refund: 0.96,
      technical: 0.01,
      sales: 0.01,
      account: 0.01,
      other: 0.01,
    },
    suggested_team: "财务支持",
    needs_review: true,
    elapsed_ms: 1234,
    input_tokens: 140,
    model: provider === "jev" ? "jev-test" : "local-test",
    rubric_id: "test-rules",
    input_id: "same-ticket",
  };
}
function fixture(id, analyzed = true) {
  return {
    id,
    subject: id === "TK-1001" ? "订阅重复扣费" : "另一个工单",
    message: "这是一条用于交互测试的客户来信。".repeat(40),
    customer: "测试客户",
    company: "测试公司",
    channel: "邮件",
    time: "10:00",
    runs: Object.fromEntries(
      ["laya-ft", "jev"].map((p) => [
        p,
        {
          analysis: analyzed ? analysis(p) : null,
          status: analyzed ? "analyzed" : "pending",
          team: null,
          revision: 1,
          history: [{ label: "工单已收到", time: "10:00" }],
        },
      ]),
    ),
  };
}
const projected = (t, p) => ({ ...clone(t), ...clone(t.runs[p]) });
const response = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
async function mount() {
  root = createRoot(document.querySelector("#root"));
  await act(async () => {
    root.render(
      React.createElement(TicketDesk, { initialProvider: "laya-ft" }),
    );
  });
}
async function click(element) {
  assert.ok(element, "click target exists");
  await act(async () => {
    element.click();
  });
}
function button(text) {
  return [...document.querySelectorAll("button")].find((b) =>
    b.textContent.includes(text),
  );
}
async function fill(element, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      element instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype,
      "value",
    ).set.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  tickets = [fixture("TK-1001"), fixture("TK-1002", false)];
  calls = [];
  failRead = false;
  window.history.replaceState(null, "", "/laya-ft");
  global.fetch = async (url, options = {}) => {
    const parsed = new URL(url, window.location.href),
      p = parsed.searchParams.get("provider") || "laya-ft";
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ path: parsed.pathname, body, headers: options.headers });
    if (parsed.pathname === "/api/session")
      return response({ csrf_token: "test-token" });
    if (parsed.pathname === "/api/health")
      return response({
        status: "ready",
        model: "local-test",
        rubric_id: "test-rules",
        providers: {
          "laya-ft": { status: "ready", model: "local-test" },
          jev: { status: "ready", model: "jev-test" },
        },
      });
    if (parsed.pathname === "/api/tickets" && !body) {
      if (failRead) throw new TypeError("network");
      return response({
        tickets: tickets.map((t) => projected(t, p)),
        rubric_id: "test-rules",
      });
    }
    if (parsed.pathname === "/api/tickets" && body) {
      const t = fixture("TK-1003", false);
      t.subject = body.subject;
      t.message = body.message;
      tickets.unshift(t);
      return response({ ticket: projected(t, p) }, 201);
    }
    const t = tickets.find((t) => t.id === body?.id);
    if (parsed.pathname === "/api/analyze") {
      t.runs[p].analysis = analysis(p);
      t.runs[p].analysis.suggested_team = p === "jev" ? "技术支持" : "财务支持";
      t.runs[p].status = "analyzed";
    } else if (parsed.pathname === "/api/assign") {
      t.runs[p].status = "assigned";
      t.runs[p].team = body.team;
    } else if (parsed.pathname === "/api/reopen") {
      t.runs[p].status = "analyzed";
      t.runs[p].team = null;
    } else throw new Error("Unexpected request " + url);
    t.runs[p].revision++;
    return response({ ticket: projected(t, p) });
  };
});
afterEach(async () => {
  if (root) {
    await act(async () => root.unmount());
    root = null;
  }
  document.querySelector("#root").replaceChildren();
});

test("important decisions visible; history and detailed scores expand on demand", async () => {
  await mount();
  assert.match(
    document.querySelector(".decision-summary").textContent,
    /P1.*流失风险.*退款诉求/,
  );
  assert.equal(document.querySelector(".analysis-details").open, false);
  assert.equal(document.querySelector(".history-section").open, false);
  assert.ok(button("确认分配"));
  assert.equal(button("确认分配").disabled, false);
  await click(document.querySelector(".analysis-details > summary"));
  assert.equal(document.querySelector(".analysis-details").open, true);
  assert.equal(document.querySelectorAll(".signal").length, 3);
  const preview = document.querySelector(".customer-message").textContent;
  assert.ok(preview.length < tickets[0].message.length);
  await click(button("展开完整来信"));
  assert.equal(
    document.querySelector(".customer-message").textContent,
    tickets[0].message,
  );
  await click(button("收起来信"));
  assert.equal(
    document.querySelector(".customer-message").textContent,
    preview,
  );
});

test("comparison reads saved results without calling a model and highlights actual differences", async () => {
  await mount();
  await click(button("模型对照"));
  assert.equal(
    document.querySelectorAll(".comparison-table tr.different").length,
    1,
  );
  assert.ok(calls.every((c) => c.path !== "/api/analyze"));
  await click(document.querySelector(".jev-card button"));
  const call = calls.find((c) => c.path === "/api/analyze");
  assert.equal(call.body.provider, "jev");
  assert.equal(call.headers["X-CSRF-Token"], "test-token");
  await click(button("工单详情"));
  assert.equal(
    document.querySelector(".suggestion-heading h2").textContent,
    "财务支持",
  );
});

test("low confidence requires a manual team; assignment and reopening retain model isolation", async () => {
  tickets[0].runs["laya-ft"].analysis.confidence = 0.3;
  await mount();
  assert.equal(button("确认分配").disabled, true);
  await act(async () => {
    const select = document.querySelector("#team-choice");
    select.value = "客户成功";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  assert.equal(button("确认分配").disabled, false);
  await click(button("确认分配"));
  assert.equal(
    calls.find((c) => c.path === "/api/assign").body.expected_revision,
    1,
  );
  assert.equal(tickets[0].runs.jev.status, "analyzed");
  await click(button("重新打开工单"));
  assert.equal(tickets[0].runs["laya-ft"].status, "analyzed");
  assert.equal(tickets[0].runs["laya-ft"].team, null);
});

test("switching tickets updates URL, clears disclosure state and preserves model query links", async () => {
  await mount();
  await click(document.querySelector(".analysis-details > summary"));
  await click(button("另一个工单"));
  assert.equal(
    new URL(window.location.href).searchParams.get("ticket"),
    "TK-1002",
  );
  assert.equal(document.querySelector(".subject").textContent, "另一个工单");
  assert.equal(
    document
      .querySelector('.provider-switch a[href^="/jev"]')
      .getAttribute("href"),
    "/jev?ticket=TK-1002",
  );
  assert.ok(button("使用 Laya 分析"));
});

test("search empty state and refresh failure preserve existing tickets", async () => {
  await mount();
  await fill(document.querySelector('[aria-label="搜索工单"]'), "找不到的内容");
  assert.equal(document.querySelectorAll(".ticket-row").length, 0);
  assert.match(document.querySelector(".empty-list").textContent, /没有匹配/);
  await click(document.querySelector('[aria-label="清除搜索"]'));
  assert.equal(document.querySelectorAll(".ticket-row").length, 2);
  failRead = true;
  await click(document.querySelector('[aria-label="刷新工单"]'));
  assert.match(
    document.querySelector('[role="alert"]').textContent,
    /无法连接/,
  );
  assert.equal(document.querySelectorAll(".ticket-row").length, 2);
});

test("new ticket sends an idempotency key and shows saved content without executing HTML", async () => {
  await mount();
  await click(button("新建工单"));
  await fill(
    document.querySelector("#ticket-subject"),
    "<img src=x onerror=alert(1)>",
  );
  await fill(
    document.querySelector("#ticket-message"),
    "Synthetic content only",
  );
  await act(async () =>
    document
      .querySelector(".dialog form")
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  const created = calls.find((c) => c.path === "/api/tickets" && c.body);
  assert.match(created.body.request_id, /^[a-f0-9-]{36}$/);
  assert.equal(
    document.querySelector(".subject").textContent,
    "<img src=x onerror=alert(1)>",
  );
  assert.equal(document.querySelector(".reading-pane img"), null);
  assert.equal(document.querySelector("dialog").open, false);
});

test("analyzing from the pending filter keeps the completed ticket in view", async () => {
  await mount();
  await click(
    [...document.querySelectorAll(".filters button")].find(
      (b) => b.textContent === "待分析",
    ),
  );
  assert.equal(document.querySelector(".subject").textContent, "另一个工单");
  await click(button("使用 Laya 分析"));
  assert.equal(document.querySelector(".subject").textContent, "另一个工单");
  assert.ok(button("确认分配"));
});

test("batch stop finishes the active ticket without starting the next request", async () => {
  tickets = [fixture("TK-1001", false), fixture("TK-1002", false)];
  const originalFetch = global.fetch;
  let release;
  const waiting = new Promise((resolve) => {
    release = resolve;
  });
  global.fetch = async (url, options) => {
    if (url.startsWith("/api/analyze")) await waiting;
    return originalFetch(url, options);
  };
  await mount();
  await click(button("分析待处理工单"));
  await click(button("完成当前后停止"));
  await act(async () => {
    release();
  });
  assert.equal(calls.filter((c) => c.path === "/api/analyze").length, 1);
  assert.equal(tickets[0].runs["laya-ft"].status, "analyzed");
  assert.equal(tickets[1].runs["laya-ft"].status, "pending");
});
