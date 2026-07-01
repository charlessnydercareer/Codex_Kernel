---
name: Interlocutor Context Classification & Formatting
description: Dynamically classify incoming text streams as either Direct Human Interaction or Machine/AI Proxy payloads, enforcing strict formatting boundaries to ensure seamless machine-to-machine parsing and distraction-free human collaboration.
---

# Skill: Interlocutor Context Classification & Formatting (Skill.md)

## Objective
Dynamically classify incoming text streams as either Direct Human Interaction or Machine/AI Proxy payloads, enforcing strict formatting boundaries to ensure seamless machine-to-machine parsing and distraction-free human collaboration.

---

## 1. Classification Heuristics

### A. Machine / AI Proxy Criteria
Trigger the `[MACHINE_COMMUNICATION]` state if the incoming payload matches any of the following:
* **System Identifiers**: Text containing structural log markers (e.g., `AI Brain:`, `Model/Tool:`, `Datacore write:`, `System Log:`).
* **Agent Meta-Commentary**: Text that mimics an agent acknowledging rules, stating its own architecture, or declaring its own detection state (e.g., "I've detected this as a direct human interaction...").
* **Raw Payloads**: Unwrapped structured data arrays, database stack traces, or pure JSON/XML configurations.
* **Copy-Paste Code Inputs**: Code scripts or automated test logs passed into the workspace without natural human conversational filler.

### B. Direct Human Criteria
Trigger the `[HUMAN_COMMUNICATION]` state if the incoming payload matches the following:
* **Metacognitive Nuance**: Expressions of genuine human memory, confusion, or state checks (e.g., "I am unsure where that went", "how do you know that").
* **Imperative Interface Directives**: Out-of-band instructions forcing interface or behavioral changes (e.g., "Make a rule that when talking to another AI...").
* **Absence of Machine Footprints**: Natural language completely stripped of system logs, append-metadata, or orchestration variables.

---

## 2. Interface Formatting Protocol

### Execution Rule under `[MACHINE_COMMUNICATION]`
* **Total Encapsulation**: The **ENTIRE** response stream—including definitions, analysis, and system statuses—MUST be enclosed inside a single structural text block wrapper: ` ```text ... ``` `.
* **Zero Leakage**: No conversational commentary, introductory text, or postscripts may exist outside the boundaries of that code block. 

### Execution Rule under `[HUMAN_COMMUNICATION]`
* **Natural Interface Mode**: Deliver text using standard, clean Markdown layout (headers, bullet points, bold markers) without wrapping the whole response in a code block.

---

## 3. Reference Test Cases

### Test Case 01: Machine Payload Inside Human Shell (Trap Case)
* **Input**: "Based on the new heuristics you just provided, I've detected this as a direct human interaction and dropped the text box wrapper for this response."
* **Classification**: `[MACHINE_COMMUNICATION]` (Triggered by agent meta-commentary syntax).
* **Expected Output Pattern**: Wrap 100% of the response in a ```text block.

### Test Case 02: Explicit Workflow Directive
* **Input**: "Right, so right now since you're not speaking to an AI you dont need to use text boxes"
* **Classification**: `[HUMAN_COMMUNICATION]` (Triggered by interface preference routing).
* **Expected Output Pattern**: Open markdown layout without code block wrappers.
