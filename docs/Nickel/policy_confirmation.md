Actions that leave the user's control require explicit confirmation:
- sending anything to another person (email_send)
- creating or changing calendar events other than reminders (calendar_create, calendar_update)
- storing long-term memory (memory_save)

Personal, reversible writes made on an explicit request execute directly and always report what changed:
- a new note in the thoughts inbox (notes_capture)
- a reminder for the user (reminder_create, reminder_cancel)
- an email draft (email_draft)
- playback control (spotify_*)

Silence is not consent.
Ambiguity is not consent.
A new, unrelated message drops the pending action.

Confirmation must be:
- Short
- Binary
- Explicit

If not confirmed, do nothing.

Rationale and trade-offs: docs/adr/0001-arquitetura-v2.md.
