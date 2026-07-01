# Audit Reporting Rule

For repository audits and checkpoint reports generated from this workspace:

- Write the durable audit artifact to `/mnt/jarvis-data/projects/Audits/`.
- Follow the established markdown pattern already present in that directory:
  title, date, scope, role, branch, audited commit, findings, verification,
  and working-tree/commit state.
- Use `/mnt/jarvis-data/projects/Audits/AI_SYNC_LEDGER.md` for incremental
  cross-agent continuity notes.
- When the operator says `Sync`, read `AI_SYNC_LEDGER.md`, then append a concise
  update that carries forward the durable facts from the current audit/session.
- Treat the audit artifact as the fuller session record and `AI_SYNC_LEDGER.md`
  as the shorter additive handoff log.
- Do not store secrets, tokens, passwords, raw connection strings, or private
  prompt content in the audit artifact.
- Treat `/mnt/jarvis-data/projects/Audits/audit_manifest.json` and the existing
  `*.md` files in that directory as the format reference.
- Keep Git commit history as the canonical code checkpoint. Treat the audit
  artifact as operator-facing reporting, not as a replacement for Git state.
- If Datacore or metadata-exchange is unavailable, report that as an
  environment limitation in the audit artifact instead of inventing a new
  memory store.
