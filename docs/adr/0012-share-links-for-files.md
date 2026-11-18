# 0012 - Share links are token links to one file

## Context

Owners want to hand a file to someone without an account. A link is a public surface: anyone on the internet can try tokens.

## Decision

- A link points to **one file**, is **view-only** (name, size, type and a short-lived download URL), and **expires** (required, 1 to 30 days). There is no password and no listing. A folder link is not built.
- The token is 32 random bytes (`secrets.token_urlsafe`). **Only its SHA-256 is stored**; the raw token is returned once, when the link is created. Lookup is by the hash, so no token comparison happens in application code.
- The token travels in the **body** of POST requests, not in the URL, so it does not appear in access logs; the shareable link puts it in the URL fragment, which is never sent to a server.
- Every failure (unknown token, expired, revoked, file deleted, file not ready) is one identical `404 link_not_found`, so a caller learns nothing about which links exist.
- The public endpoints are rate limited per client address. Each file has at most 20 active links.
- Link creation and revocation are recorded in the owner's audit trail (`share_link.*`). A download is recorded with no actor and the link id, **at most once per link per minute** (`last_downloaded_at`), and the endpoints are also limited per token, so a holder cannot fill the trail. Creating a link locks the file row, so the 20-link cap cannot be raced past.
- A link follows the file: deleting it or any state other than `ready` makes the link unusable immediately. Revoking is immediate and idempotent.

## Consequences

- A revoke that lands between a download's lookup and its commit can still hand out one URL; that URL is short-lived.
- Anyone who has the token can download until expiry; the owner's control is revoke and short expiry.
- Downloads are counted per request for the audit trail, not per distinct person.
- A link cannot be extended; create a new one.
