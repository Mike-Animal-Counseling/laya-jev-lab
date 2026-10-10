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
let root, tickets, calls, failRead, importErrors, failImport, connections;
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
  const items = [...document.querySelectorAll("button")];
  return items.find((b) => b.textContent.trim() === text) || items.find((b) => b.textContent.includes(text));
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
  importErrors = false;
  failImport = false;
  connections = {email: false, zendesk: false, api: false};
  window.history.replaceState(null, "", "/laya-ft");
  global.fetch = async (url, options = {}) => {
    const parsed = new URL(url, window.location.href),
      p = parsed.searchParams.get("provider") || "laya-ft";
    const upload = options.body instanceof Blob;
    const body = options.body && !upload ? JSON.parse(options.body) : null;
    calls.push({ path: parsed.pathname, body, headers: options.headers });
    if (parsed.pathname === "/api/session")
      return response({ csrf_token: "test-token" });
    if (parsed.pathname === "/api/intake/status") return response(connections);
    if (parsed.pathname === "/api/import/preview" || parsed.pathname === "/api/intake/preview") {
      if (parsed.pathname === "/api/import/preview") assert.ok(upload);
      return response({ sheet: "Tickets", ready: importErrors ? 0 : 1, duplicates: 0, errors: importErrors ? 1 : 0, available: 98,
        rows: [{row: 2, status: importErrors ? "error" : "ready", issue: importErrors ? "Message is required." : "", ticket: importErrors ? {} : {
          subject: "Imported demo", message: "Synthetic feedback", customer: "Demo user", company: "Example team", channel: "Excel",
        }}] });
    }
    if (parsed.pathname === "/api/import") {
      if (failImport) return response({ error: "Nothing saved. Try again." }, 503);
      const imported = fixture("TK-1003", false);
      Object.assign(imported, body.rows[0]);
      tickets.unshift(imported);
      return response({ tickets: tickets.map((t) => projected(t, p)), imported: 1, skipped: 0 }, 201);
    }
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
    } else if (parsed.pathname === "/api/resolve") {
      t.runs[p].status = "done";
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
    /P1.*Churn risk.*Refund/,
  );
  assert.equal(document.querySelector(".analysis-details").open, false);
  assert.equal(document.querySelector(".history-section").open, false);
  assert.ok(button("Assign"));
  assert.equal(button("Assign").disabled, false);
  await click(document.querySelector(".analysis-details > summary"));
  assert.equal(document.querySelector(".analysis-details").open, true);
  assert.equal(document.querySelectorAll(".signal").length, 3);
  const preview = document.querySelector(".customer-message").textContent;
  assert.ok(preview.length < tickets[0].message.length);
  await click(button("Read more"));
  assert.equal(
    document.querySelector(".customer-message").textContent,
    tickets[0].message,
  );
  await click(button("Show less"));
  assert.equal(
    document.querySelector(".customer-message").textContent,
    preview,
  );
});

test("comparison reads saved results without calling a model and highlights actual differences", async () => {
  await mount();
  await click(button("Compare"));
  assert.equal(
    document.querySelectorAll(".comparison-table tr.different").length,
    1,
  );
  assert.ok(calls.every((c) => c.path !== "/api/analyze"));
  await click(document.querySelector(".jev-card button"));
  const call = calls.find((c) => c.path === "/api/analyze");
  assert.equal(call.body.provider, "jev");
  assert.equal(call.headers["X-CSRF-Token"], "test-token");
  await click(button("Ticket"));
  assert.equal(
    document.querySelector(".suggestion-heading h2").textContent,
    "Billing",
  );
});

test("low confidence requires a manual team; assignment and reopening retain model isolation", async () => {
  tickets[0].runs["laya-ft"].analysis.confidence = 0.3;
  await mount();
  assert.equal(button("Assign").disabled, true);
  await act(async () => {
    const select = document.querySelector("#team-choice");
    select.value = "客户成功";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  assert.equal(button("Assign").disabled, false);
  await click(button("Assign"));
  assert.equal(
    calls.find((c) => c.path === "/api/assign").body.expected_revision,
    1,
  );
  assert.equal(tickets[0].runs.jev.status, "analyzed");
  await click(button("Reopen"));
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
  assert.ok(button("Analyze"));
});

test("search empty state and refresh failure preserve existing tickets", async () => {
  await mount();
  await fill(document.querySelector('[aria-label="Search tickets"]'), "no matching text");
  assert.equal(document.querySelectorAll(".ticket-row").length, 0);
  assert.match(document.querySelector(".empty-list").textContent, /No matches/);
  await click(document.querySelector('[aria-label="Clear search"]'));
  assert.equal(document.querySelectorAll(".ticket-row").length, 2);
  failRead = true;
  await click(document.querySelector('[aria-label="Refresh"]'));
  assert.match(
    document.querySelector('[role="alert"]').textContent,
    /Local service unavailable/,
  );
  assert.equal(document.querySelectorAll(".ticket-row").length, 2);
});

test("new ticket sends an idempotency key and shows saved content without executing HTML", async () => {
  await mount();
  await click(button("New ticket"));
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
      (b) => b.textContent === "Pending",
    ),
  );
  assert.equal(document.querySelector(".subject").textContent, "另一个工单");
  await click(button("Analyze"));
  assert.equal(document.querySelector(".subject").textContent, "另一个工单");
  assert.ok(button("Assign"));
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
  await click(button("Analyze all"));
  await click(button("Stop"));
  await act(async () => {
    release();
  });
  assert.equal(calls.filter((c) => c.path === "/api/analyze").length, 1);
  assert.equal(tickets[0].runs["laya-ft"].status, "analyzed");
  assert.equal(tickets[1].runs["laya-ft"].status, "pending");
});

async function uploadFile() {
  await act(async () => {
    const input = document.querySelector('[aria-label="Import file"]');
    Object.defineProperty(input, "files", { configurable: true, value: [new File(["test workbook"], "tickets.xlsx")] });
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

test("Excel import previews locally and a failed save retains its retry identity", async () => {
  await mount();
  await click(document.querySelector(".import-trigger"));
  assert.equal(button("Import tickets").disabled, true);
  await uploadFile();
  assert.equal(tickets.length, 2);
  assert.equal(document.querySelectorAll(".import-preview tbody tr").length, 1);
  assert.equal(calls.filter((c) => c.path === "/api/import").length, 0);
  failImport = true;
  await click(button("Import 1 ticket"));
  assert.equal(document.querySelector("dialog").open, true);
  const firstKey = calls.find((c) => c.path === "/api/import").body.request_id;
  failImport = false;
  await click(button("Import 1 ticket"));
  assert.equal(calls.filter((c) => c.path === "/api/import")[1].body.request_id, firstKey);
  assert.equal(tickets.length, 3);
  assert.equal(document.querySelector(".subject").textContent, "Imported demo");
  assert.equal(document.querySelector("dialog").open, false);
  assert.equal(calls.filter((c) => c.path === "/api/analyze").length, 0);
});

test("Excel row errors block import and preserve the inbox", async () => {
  importErrors = true;
  await mount();
  await click(document.querySelector(".import-trigger"));
  await uploadFile();
  assert.equal(button("Import tickets").disabled, true);
  assert.match(document.querySelector(".import-preview").textContent, /Message is required/);
  await click(button("Cancel"));
  assert.equal(tickets.length, 2);
  assert.equal(calls.filter((c) => c.path === "/api/import").length, 0);
});

test("Zendesk sync requires configuration and remains a preview until confirmed", async () => {
  await mount();
  await click(document.querySelector(".import-trigger"));
  await click(button("Zendesk"));
  assert.equal(button("Sync").disabled, true);
  await click(button("Cancel"));
  connections.zendesk = true;
  await click(document.querySelector(".import-trigger"));
  await click(button("Zendesk"));
  assert.equal(button("Sync").disabled, false);
  await click(button("Sync"));
  assert.deepEqual(calls.find((c) => c.path === "/api/intake/preview").body, {source: "zendesk", provider: "laya-ft"});
  assert.equal(tickets.length, 2);
  assert.equal(calls.filter((c) => c.path === "/api/import").length, 0);
  assert.equal(document.querySelectorAll(".import-preview tbody tr").length, 1);
  await click(button("Excel / CSV"));
  assert.equal(document.querySelector(".import-preview"), null);
  assert.equal(button("Import tickets").disabled, true);
});

test("Done moves a ticket out of Inbox and Reopen restores its active state", async () => {
  await mount();
  await click(document.querySelector(".resolve-action"));
  assert.equal(document.querySelectorAll(".ticket-row").length, 1);
  assert.equal(tickets[0].runs["laya-ft"].status, "done");
  assert.equal(tickets[0].runs.jev.status, "analyzed");
  await click(document.querySelector('nav [aria-label="Done"]'));
  assert.equal(document.querySelector(".subject").textContent, tickets[0].subject);
  await click(document.querySelector(".resolve-action"));
  assert.equal(tickets[0].runs["laya-ft"].status, "analyzed");
  assert.equal(document.querySelectorAll(".ticket-row").length, 2);
});
