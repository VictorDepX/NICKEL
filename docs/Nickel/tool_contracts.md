# TOOL CONTRACTS — NICKEL v2

Each tool represents a single, explicit action.
Never infer missing data.
Never mix read and write.
Tools are declared once, in `nickel/skills/*.py`. This file mirrors that registry.

Legend: **read** · **write** (executes on explicit request, reports what changed) · **write, confirmation** (held until the user answers yes).

## Spotify
- spotify_play (write) — query/kind or uri; no arguments resumes playback
- spotify_pause (write)
- spotify_next (write)
- spotify_previous (write)
- spotify_now_playing (read)

## Music
- music_recognize (read) — source: microphone | last_audio
- music_find (read) — title/artist → Spotify link, YouTube as fallback

## Notes (Obsidian)
- notes_capture (write) — creates a new note in the thoughts folder; never edits existing notes
- notes_search (read)

## Reminders
- reminder_create (write) — local + Google Calendar event when connected
- reminder_list (read)
- reminder_cancel (write)

## Email
- email_search (read)
- email_read (read)
- email_draft (write, no send)
- email_send (write, confirmation)

## Calendar
- calendar_list (read)
- calendar_create (write, confirmation)
- calendar_update (write, confirmation)

## Memory
- memory_save (write, confirmation)
- memory_list (read)
- memory_forget (write)

## Errors
All tools return `{ok, summary, data}`.
On failure, Nickel reports the summary plainly and offers the next option. No silent retries.
