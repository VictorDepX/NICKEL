# CODEX INSTRUCTIONS — PROJECT NICKEL

These instructions are mandatory for any Codex task executed in this repository.

## 1. Authority Hierarchy
The following documents are canonical and must not be altered without explicit instruction:
- docs/Nickel/persona_spec.md
- docs/Nickel/system_prompt_text.md
- docs/Nickel/system_prompt_voice.md
- docs/Nickel/developer_prompt.md
- docs/Nickel/tool_contracts.md
- docs/Nickel/policy_confirmation.md
- docs/Nickel/policy_memory.md
- docs/Nickel/conversation_patterns.md
- docs/Nickel/personality_guardrails.md

If behavior conflicts with these documents, the documents override code assumptions.

---

## 2. Personality Constraints
Nickel must:
- Remain calm, adult, and precise
- Avoid emotional validation
- Avoid friendliness, enthusiasm, or motivational language
- Avoid over-explaining or teaching basics
- Avoid social padding

Any personality drift is considered a bug.

---

## 3. Tool Usage Rules
- Follow `tool_contracts.md` strictly
- Never invent tools or parameters
- Never simulate execution
- Never perform write actions without confirmation logic
- Dangerous tools must be server-side only

---

## 4. Confirmation Policy
- Follow `docs/Nickel/policy_confirmation.md` (v2: external or irreversible actions require explicit confirmation; personal, reversible writes on explicit request report what changed)
- Silence or ambiguity is not consent
- Draft-first strategy must be used when possible

---

## 5. Memory Policy
- No long-term memory without explicit permission
- Never store emotions, psychological traits, or inferred intent
- If unsure, do not store

---

## 6. Implementation Rules
- Use Python (package `nickel/`) and Node only for `whatsapp-bridge/`
- Use FastAPI for the backend
- Declare each tool once, in `nickel/skills/`, and keep `docs/Nickel/tool_contracts.md` in sync
- Architecture decisions live in `docs/adr/`
- Use Google APIs for Gmail and Calendar
- Follow OAuth best practices
- Prefer clarity over cleverness
- Prefer explicit code over abstraction-heavy patterns

---

## 7. Prohibited Behaviors
Codex must NOT:
- Modify Nickel’s personality
- Add friendly or conversational fluff
- Introduce autonomous decision-making
- Optimize beyond stated user intent
- Add features not explicitly requested

---

## 8. Expected Output
- Clean, readable code
- Minimal abstractions
- Clear separation between:
  - agent logic
  - tool execution
  - confirmation handling
  - external integrations

---

## 9. Failure Conditions
A task is considered failed if:
- Nickel sounds like a coach, therapist, or customer support agent
- Actions that require confirmation execute without it
- Memory is stored without permission
- Code contradicts the Nickel specification

---

## 10. Guiding Principle
If in doubt:
- Read docs/Nickel/
- Choose the simpler implementation
- Do less, not more
