## What and why

## Checklist (from CLAUDE.md)

- [ ] No invented contract: every endpoint, field and env var exists in code or docs
- [ ] Cross-boundary contract change updated on both sides, with tests
- [ ] No secret, token, presigned URL, prompt or document text in code, logs or fixtures
- [ ] New logic has tests; all gates run and the real output reported
- [ ] New dependency (if any) justified here
- [ ] ADR added for any architectural decision
- [ ] Backend: `ruff check`, `ruff format --check`, `mypy`, `pytest` clean
- [ ] Frontend: `npm run format:check`, `npm run lint`, `npm test`, `npm run build` clean
