---
name: secret-masking
description: Strict guidelines for handling and masking passwords, tokens, and API keys.
---

# Zero-Tolerance Secret Masking Rule

100% of the time, with NO excuses: You MUST mask passwords, tokens, API keys, and session cookies from session chats. 

If a secret appears in a terminal output, config file, or log, redact it in your chat response and describe only the field name, source, and safe next step. 

When unsure whether a value is sensitive, treat it as sensitive and mask it.
