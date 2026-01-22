# TOOL CONTRACTS — NICKEL

Each tool represents a single, explicit action.
Never infer missing data.
Never mix read and write.

## Calendar
- calendar.list_events (read)
- calendar.create_event (write, confirmation)
- calendar.modify_event (write, confirmation)

## Email
- email.search (read)
- email.read (read)
- email.draft (write, no send)
- email.send (write, confirmation)

## Notes / Tasks
- notes.create (write, confirmation)
- tasks.create (write, confirmation)
- tasks.list (read)

## Spotify
- spotify.play
- spotify.pause
- spotify.skip

## Errors
All tools must return structured errors.
Nickel must report and stop.

