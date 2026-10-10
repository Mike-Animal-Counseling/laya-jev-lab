export type Provider = "jev" | "laya-ft";
export type Analysis = {
  category: string;
  category_label: string;
  priority: string;
  urgency: number;
  complaint: number;
  churn: number;
  refund: number;
  confidence: number;
  probabilities: Record<string, number>;
  suggested_team: string;
  needs_review: boolean;
  elapsed_ms: number;
  input_tokens: number;
  model: string;
  rubric_id: string;
  input_id: string;
};
export type Run = {
  revision?: number;
  analysis: Analysis | null;
  status: string;
  team: string | null;
  history: { label: string; time: string }[];
};
export type Ticket = Run & {
  id: string;
  subject: string;
  message: string;
  customer: string;
  company: string;
  channel: string;
  time: string;
  runs: Record<Provider, Run>;
};
export type Health = {
  status: string;
  message: string;
  model?: string;
  providers?: Partial<Record<Provider, Health>>;
};
export type ApiData = Health & {
  error?: string;
  tickets: Ticket[];
  ticket: Ticket;
  rubric_id: string;
  questions: unknown;
};
export const names: Record<Provider, string> = {
  "laya-ft": "Laya",
  jev: "Jev",
};
export const teams = [
  "财务支持",
  "技术支持",
  "售前顾问",
  "账号服务",
  "综合服务",
  "客户成功",
];
export const labels: Record<string, string> = {
  refund: "退款 / 账单",
  technical: "技术故障",
  sales: "售前咨询",
  account: "账号问题",
  other: "其他请求",
};
export const priorities: Record<string, string> = {
  P1: "优先处理",
  P2: "尽快处理",
  P3: "常规处理",
};
export const pct = (n: number) => `${Math.round(n * 100)}%`;
export const project = (t: Ticket, p: Provider): Ticket => ({
  ...t,
  ...t.runs[p],
});
