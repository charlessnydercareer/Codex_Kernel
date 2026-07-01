# Codex Nexus Agent Guide

This repository follows the Nexus shared execution model, with a narrowed local
copy of the skills and rules that are useful for `codex_nexus`.

## Local Skills

The following reviewed skills are vendored under `/mnt/jarvis-data/projects/codex_nexus/skills/`:

- `accidental-data-loss-prevention`
- `agent9-metadata-exchange`
- `interlocutor-classification`
- `karpathy-guidelines`
- `managing-python-dependencies`
- `secret-masking`

Use these local copies as the repo reference set for safety, reporting, and
execution discipline.

## Core Rules

- Prefer the shared Nexus tooling and existing architecture over one-off local
  replacements.
- Use Datacore task memory when it is actually available.
- If Datacore is unavailable, report the exact blocker and do not invent a new
  competing memory store.
- Keep Git history as the canonical implementation checkpoint.
- Write operator-facing audit artifacts to `/mnt/jarvis-data/projects/Audits/`
  using the established markdown format already present there.
- Do not store secrets, tokens, passwords, raw connection strings, private
  prompts, or secret-bearing logs in code, docs, tests, audits, or memory.
- Mask sensitive values in all chat and report output.
- Favor the smallest safe change. Do not broaden a bounded task into a redesign.
- Touch only the files required for the current task.
- Add targeted verification for the changed behavior and report exact checks run.

## Boundaries

- No automatic application submission.
- No unauthorized email send, draft-send, or mailbox mutation.
- No destructive data-loss operations without explicit user approval.
- No new per-agent MCP configs or standalone memory databases unless explicitly
  requested.

## Reporting

- Audit/report markdown for this workspace belongs under
  `/mnt/jarvis-data/projects/Audits/`.
- Use existing audits in that directory plus `audit_manifest.json` as the format
  reference.
- Cross-agent incremental handoff notes belong in
  `/mnt/jarvis-data/projects/Audits/AI_SYNC_LEDGER.md`.
- When the operator says `Sync`, read `/mnt/jarvis-data/projects/Audits/AI_SYNC_LEDGER.md`
  first, then append a concise incremental update derived from the durable facts
  already captured in the current audit/session. Every appended entry must follow
  the ledger block format (Timestamp · Ledger ID · Audit File · Scope · Outcome · Agent).
- Treat `/mnt/jarvis-data/projects/Audits/` as the fuller session-style record
  and `/mnt/jarvis-data/projects/Audits/AI_SYNC_LEDGER.md` as the shorter
  continuity layer for the next agent.
- When a browser audit is performed, save evidence bundles separately and do not
  commit private screenshots.
- Task reports in chat must still end with the required executor footer imposed
  by the active agent runtime.
