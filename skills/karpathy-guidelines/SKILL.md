---
name: nexus-karpathy-guidelines
description: Shared Nexus coding-agent execution discipline adapted from Karpathy-style guidelines. Use when writing, reviewing, or refactoring Nexus code to avoid overcomplication, preserve HITL safety boundaries, make surgical changes, use Datacore memory when available, and verify success criteria.
license: MIT-adapted-from-upstream
---

# Nexus Karpathy Guidelines

Shared behavioral guidance for Nexus coding agents.

Adapted from the Andrej Karpathy-inspired coding guidelines package. This is **not a runtime skill** and must not add application behavior by itself. It is operating discipline for Claude Code, Cursor/Composer2, Codex, Antigravity, and future coding agents working in the Nexus repo.

## Purpose

Reduce common coding-agent failure modes in Nexus:

- overbuilding instead of solving the requested slice
- touching unrelated files
- creating speculative abstractions
- skipping verification
- weakening HITL boundaries
- forgetting Datacore memory/read/write discipline
- producing task reports that cannot be reconciled later

## 0. Datacore First

Before assuming prior Nexus task state, use the Datacore (`hindsight-nexus-db`) when available.

Preferred MCP operations when exposed:

- `metadata_exchange_lookup` to search relevant prior worker completions, decisions, and context
- `metadata_exchange_get_entity` when a specific entity is known
- `metadata_exchange_record_task_completion` after the task is complete

Record only structured durable facts:

- request ID
- executor name/tool
- branch or commit when available
- files changed
- tests run and results
- boundary confirmation
- blockers or follow-up facts

Do **not** write secrets, tokens, raw environment values, pasted logs containing secrets, screenshots with secrets, or private email/body content to the Datacore.

If the Datacore is unavailable, do not create a competing memory store unless the operator explicitly asks. Report the exact blocker in the final footer.

## 1. Think Before Coding

Do not assume. Do not hide uncertainty. Surface constraints early.

Before implementing:

- Read the task contract, nearby code, and relevant tests.
- Query Datacore memory/context when available.
- State what context was found, or state that memory was unavailable.
- Identify the smallest safe change that satisfies the request.
- Ask only when the ambiguity blocks safe implementation.
- Do not turn a bounded implementation task into a broad redesign.

For Nexus, "think first" also means checking:

- Does this touch application submission?
- Does this touch email send/draft/mailbox mutation?
- Does this touch secrets?
- Does this create a new durable memory or backup path?
- Does this change runtime behavior or only docs/rules/tests?

## 2. Simplicity First

Minimum code that solves the task. Nothing speculative.

Rules:

- No features beyond the ticket.
- No abstractions for single-use code.
- No "future flexibility" unless the task explicitly asks for it.
- No broad rewrites when a surgical patch works.
- No new dependency unless clearly justified.
- No runtime service, cron job, or background worker unless explicitly requested.
- Prefer static tests for static contracts.
- Prefer deterministic tests over browser/runtime tests unless UI behavior requires browser proof.

Ask:

> Would a senior engineer reviewing this diff say it is larger than the task?

If yes, reduce it.

## 3. Surgical Changes

Touch only what the task requires.

When editing existing code:

- Do not improve adjacent code unless required.
- Do not rename agents, services, routes, packages, or concepts unless explicitly requested.
- Match existing style.
- Keep imports, file layout, and naming consistent with the repo.
- Remove only dead code introduced by your own change.
- Mention unrelated problems in the report; do not fix them unless they block the task.

Every changed line should trace back to the request.

## 4. Goal-Driven Execution

Define success criteria and verify them.

For every Nexus task:

1. Identify the intended file/API/UI/doc change.
2. Add or update tests appropriate to the slice.
3. Run the narrowest useful verification first.
4. Run broader checks when practical.
5. Report exact commands and results.

Examples:

- "Add a UI badge" -> static test for rendered text/fields, then frontend lint/build if relevant.
- "Add read-only endpoint" -> API unit test, secret-hygiene check, no-mutation boundary check.
- "Add agent rule" -> static test that required rule/footer/boundary strings exist.
- "Fix import drift" -> targeted failing tests, then non-Postgres suite if practical.

## Nexus Safety Boundaries

These boundaries override generic coding-agent guidance.

### Application submission

Never add automatic application submission.

Do not add, restore, or enable:

- no-auto-submit bypasses
- browser submit clicks
- apply-now automation
- hidden submission side effects
- lifecycle mutation without explicit operator action

Approval means submit-ready acknowledgment only unless a human operator performs the external submission and records evidence.

### Email and mailbox safety

Never add unauthorized email behavior.

Do not add or modify behavior that:

- sends email automatically
- sends drafts automatically
- mutates mailbox state
- archives/deletes/moves messages
- marks messages read/unread
- creates outbound recruiter communication without explicit authorization

Drafting or sending must remain explicitly operator-authorized and auditable.

### Secrets

Never put secrets in:

- source files
- docs
- tests
- Datacore memory
- task reports
- screenshots
- fixtures
- command output pasted into reports

Use variable names only. Redact values.

## Required Final Report Footer

Every Nexus task report must end with this exact four-line footer and nothing after it:

```text
AI Brain: <executor name>
Model/Tool: <model or tool name if known>
Role: <implementation / review / reconciliation / audit / etc.>
Datacore write: <recorded / unavailable — reason>
```

Do not substitute alternate labels.

Do not add lines after the footer.

## Success Signal

These guidelines are working when Nexus diffs are:

- smaller
- easier to review
- safer around HITL boundaries
- backed by targeted tests
- clearly reported
- easy to reconcile across Claude Code, Composer2, Codex, and Antigravity
