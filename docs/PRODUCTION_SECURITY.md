# Deployment security

Keep the evaluation demo on loopback. Shared deployments must use `service.server`, with authenticated workspaces and the HTTPS edge documented in [DEPLOYMENT.md](DEPLOYMENT.md). Set one exact public origin, restrict public ports, protect storage and backups, and apply edge quotas/monitoring. Run one API replica; multi-replica SQLite operation and enterprise SSO are unsupported.

Service credentials use Fernet with an operator-owned key; ticket text remains plaintext in the private database. Rotate integration keys, review member access and keep exported customer data out of source/releases. Verify restoration before relying on backups. No default password or creator-owned provider client is bundled.

Use hashed dependency locks and preserve pinned model checks. Only load declared safetensors assets; do not enable arbitrary remote model code. CI uses synthetic data and mocked providers. Passing tests or advisory checks does not establish model accuracy, regulatory compliance or absence of vulnerabilities. See [SECURITY.md](../SECURITY.md) and [PRIVACY.md](../PRIVACY.md).
