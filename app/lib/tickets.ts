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
  refund: "Billing",
  technical: "Technical",
  sales: "Sales",
  account: "Accounts",
  other: "General",
};
export const teamLabels: Record<string, string> = {
  财务支持: "Billing",
  技术支持: "Technical",
  售前顾问: "Sales",
  账号服务: "Accounts",
  综合服务: "General",
  客户成功: "Customer success",
};
export const teamLabel = (team: string) => teamLabels[team] || team;
export const priorities: Record<string, string> = {
  P1: "Urgent",
  P2: "High",
  P3: "Normal",
};
export const pct = (n: number) => `${Math.round(n * 100)}%`;
export const project = (t: Ticket, p: Provider): Ticket => ({
  ...t,
  ...t.runs[p],
});
