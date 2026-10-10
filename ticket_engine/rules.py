TEAMS = {"refund": "财务支持", "technical": "技术支持", "sales": "售前顾问", "account": "账号服务", "other": "综合服务"}

CATEGORIES = {"refund": "退款 / 账单", "technical": "技术故障", "sales": "售前咨询", "account": "账号问题", "other": "其他请求"}

QUESTIONS = {
    "category": {"type": "choice", "instructions": "Which team owns the main requested action? Route an explicit refund to billing, even when caused by a bug. Otherwise route the problem needing resolution. Complaints alone do not change the team.",
                 "criteria": {
                     "refund": "Billing: refunds, duplicate charges, invoices, payment disputes, subscription cancellation or renewal billing.",
                     "technical": "Technical support: broken existing features, errors, outages, failed exports, integrations; not requests for new features.",
                     "sales": "Sales: pricing, purchase, trials, demos, plans and discounts. Student discount eligibility or proof belongs here, not account recovery.",
                     "account": "Account support: login, passwords, account recovery, changing linked phone or email, identity checks to regain account access.",
                     "other": "General support: suggestions, new feature requests, feedback without an actionable billing, technical, sales or account issue."}},
    "urgency": {"type": "score", "instructions": "How urgent is the stated impact or deadline? Use explicit evidence, not sentiment or topic. A routine price question is not urgent. Do not invent a deadline.",
                "criteria": ["routine or explicitly not urgent; no deadline or blocked work", "requested within days; work can continue", "due today or one person's work is blocked", "critical outage blocks the whole team or imminent delivery"]},
    "complaint": {"type": "noul", "instructions": "Is the customer expressing dissatisfaction, frustration, or a complaint about the product or service?"},
    "churn": {"type": "noul", "instructions": "Does the customer explicitly threaten or intend to cancel, stop renewing, or switch to a competitor?"},
    "refund": {"type": "noul", "instructions": "Does the customer explicitly ask to receive money back or reverse a payment?"},
}
