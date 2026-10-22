# Evidence routes

The gate answers one question: *are these local artifacts self-consistent?*
It never answers *did it actually happen remotely?* Keep the routes separate and
record which one you used.

| Route | What it proves | What it does not prove |
|---|---|---|
| Offline gate (`skytale check`) | Names, parent ids, hashes, identity lines, request ids, pointer agreement are consistent locally | Anything about remote state |
| Storage read-back (direct API) | The same bytes exist in the store, with the same size and hash | That an event was written |
| Event-store read-back | The check-out/check-in row exists with all required columns | That the store artifacts match |
| Dispatcher receipt | A dispatcher accepted and processed `request_id` / agent / source | That the receiving agent read anything |
| SDK wake / chat delivery | A prompt was handed to a new conversation | That the new conversation recovered, checked in, or resumed work |

Rules:

1. Never label a direct API write as a dispatcher receipt, or the reverse.
2. A gate PASS in a final reply must be labelled "offline structure check only".
3. A handoff is complete only when both events read back and a real new
   conversation has recovered the generation and checked in.
4. When a route is unavailable, say so; an absent receipt is a gap, not a
   substitute.
