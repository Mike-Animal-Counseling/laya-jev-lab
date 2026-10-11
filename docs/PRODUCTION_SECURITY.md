# Production security requirements

The demo is a local tool. Keep its listener on loopback and retain Host/Origin checks, upload limits and safe spreadsheet parsing. Do not publish the local demo directly on the Internet. A remote service requires authentication, tenant isolation, TLS, edge/provider quotas, private storage, retention and monitoring for ticket data.

Use the hashed model/runtime lock for reproducible dependencies and preserve artifact checksum checks. Only load the declared trusted model assets; never enable arbitrary `trust_remote_code`. The lightweight backend has its own hashed requirements.lock. Optional model downloads/runtime tests require the documented artifacts; SDK tests do not establish production model quality or regulatory compliance.
