# MFT Sovereign Institution Product Frontier Runtime Contract

Status: qualification infrastructure only. No parity or superiority promotion.

Canonical recovered overlay SHA-256: `32e83dabc02b99c5441d91edb4bd6fdc8e86d2c6bb4ab270dac40d55979b1e1a`.

Execution chain:

GitHub pinned source/control -> Modal single-container stateful ASGI runtime -> Cloudflare stateless HTTPS edge.

Non-negotiables:

- The recovered overlay is verified by SHA-256 before Modal deployment.
- Modal is restricted to one runtime container for the SQLite database. No multi-container writer topology is permitted.
- SQLite remains the authority/evidence/finance store. The edge never owns or mirrors institution truth.
- Modal persistent storage contains the SQLite database. Mutating HTTP requests force a Modal Volume commit before the response is considered remotely durable.
- Cloudflare is a stateless reverse proxy and health boundary only.
- Cloudflare authenticates to Modal with an origin secret; caller authorization remains the recovered `/v2` identity/session model.
- Any provider, origin, hash, secret, or persistence mismatch fails closed.
- Historical test results do not become remote-runtime evidence until this exact overlay executes remotely.
- Production certification additionally requires a dedicated identity-encryption root secret rather than the qualification-only domain-separated key derivation from the edge root.
