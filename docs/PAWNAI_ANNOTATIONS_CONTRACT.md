# Pawn contract: session notes and screenshots

Proposal for the Pawn repo (`pawnai`). The recorder already sends the fields
below. Pawn's queue listener ignores unknown keys today, so nothing in the
Obsidian transcript changes until this lands.

Do not revive `sync-siyuan`. The recorder still publishes that command for
older consumers, but current Pawn dispatches `push-vault` and already calls
`maybe_push_transcript_to_vault` at the end of `transcribe-diarize`
(`pawn_diarize/core/queue_listener.py`). That is the hook.

## Payload

`annotations` and `screenshots` are optional on `transcribe-diarize` only.
They are not sent on `analyze` or `sync-siyuan`. Empty lists are omitted.

`per_chunk` (short chunks): each message carries the notes and screenshots
taken since the previous publish.

`end_of_session` (default): the single message carries the full set for the take.

```json
{
  "command": "transcribe-diarize",
  "audio_paths": ["s3://bucket/session/session_01.flac"],
  "threshold": 0.2,
  "cross_file_threshold": 0.2,
  "session": "my-session-label",
  "device": "cpu",
  "annotations": [
    {"id": "ab12", "at": "2026-10-01T22:10:48+02:00", "offset_sec": 48.2, "text": "decision: ship v2"}
  ],
  "screenshots": [
    {
      "id": "cd34",
      "at": "2026-10-01T22:10:05+02:00",
      "s3_uri": "s3://bucket/session/session_shot_01.png",
      "output": "DP-1",
      "region": null
    }
  ]
}
```

`id` is a stable hex string. `at` is an ISO-8601 timestamp. It is anchored
so that `at` minus the current chunk's start time equals `offset_sec`, the
position in the whole session (pause/resume included), not the position
inside that chunk. Place the note with `offset_sec`. A non-ISO `at` is
ignored by the current transcript writer, so `at` must stay a datetime.
`region` is reserved for a future crop and is `null` today. `s3_uri` may be
`null` when the recorder saved the PNG locally but upload failed.

A note typed after the last per-chunk publish, with no further audio flushed,
stays in the recorder JSONL log and is not sent. The usual stop path flushes
the open buffer first, so the closing chunk carries those items.

## Persist by id

Deltas must be idempotent, and a later vault push must still know about items
from earlier messages. Store them keyed by session + id (a small table, or a
JSON sidecar next to session state) when the job is accepted — before
transcription — so a retry of the same message does not duplicate them.

Suggested columns: `session_id`, `kind` (`note` or `screenshot`), `item_id`,
`at`, `text` or `s3_uri`, `output`, `region`, `vault_key` (filled once the
PNG is copied into the vault).

## Annotations section

`pawn_diarize/core/vault_transcript.py` rebuilds the note and keeps
`## Annotations` via `extract_annotations`. Speakers and Transcript are
replaced. Free-typed annotation text must stay free-typed.

On each push:

1. Load stored items for the session.
2. Read the current note. If the managed speakers/transcript hash matches and
   there is no new item id, keep today's short-circuit (`unchanged`).
3. If new item ids arrived and the hash matches, still rewrite the note.
   `content_hash` ignores annotations, so the short-circuit has to learn
   about pending ids or it will drop notes that show up between transcript
   changes.
4. Inside `## Annotations`, append one bullet per new note id. Wrap each
   bullet with an HTML comment so a later push can see the id and skip it:

   ```markdown
   <!-- pawn:note:ab12 -->
   - 00:48.20 — decision: ship v2
   <!-- /pawn:note:ab12 -->
   ```

5. Leave every other line in the section alone. Do not replace the section
   with only the managed bullets. `extract_annotations` already returns the
   whole body; the merge inserts missing ids and preserves the rest, including
   the default stub until the user deletes it.

## Screenshots, first step

Until the section below exists, append one annotation bullet per screenshot
id the same way:

```markdown
<!-- pawn:shot:cd34 -->
- 22:10 — screenshot `DP-1` — s3://bucket/session/session_shot_01.png
<!-- /pawn:shot:cd34 -->
```

Obsidian cannot embed an object that lives only in the audio bucket. When the
bytes have been copied into the vault (next section), prefer the embed and
keep the `s3_uri` as a fallback line if the copy failed.

## Screenshots section

Follow-up, same change if it is cheap to do together:

Add a managed `## Screenshots` block between `## Annotations` and
`## Transcript`. The annotations regex already stops at the next `##`, so
this block is not swallowed by `extract_annotations`.

```markdown
## Screenshots

<!-- pawn:shot:cd34 -->
![[session_shot_01.png]]
22:10 · DP-1
<!-- /pawn:shot:cd34 -->
```

Copy PNG bytes into the vault with `VaultStore`, next to the transcript note
(or under a `screenshots/` prefix beside it). Record `vault_key` so a retry
does not upload twice. Rebuild this section from stored items on every push;
it is managed, like Speakers and Transcript. Keep `region` on the stored item
so a later crop can replace the file without a new id.

User-owned rule: Speakers, Transcript, and Screenshots are overwritten on
sync. Text the user typed in Annotations is not.
