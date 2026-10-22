# Adapter contracts (review candidate, not a release)

These additive modules leave the v0.1 offline gate, CLI and demo unchanged.
They are library APIs, not a commit/resume orchestrator. No provider credentials,
SDK, live dispatcher, or deployed remote acceptance result is included.

## Storage: injected object-store transport

`ObjectStoreAdapter(client, store_id)` implements `put(name, bytes)`, `get(id)`,
`list(query)` and `stat(id)`. Implement `ObjectStoreClient` against an authorized
provider, passing credentials to that client outside the package. The configured
store id scopes every transport operation; do not substitute a folder label.

`StoredFile` carries `file_id`, `name`, `parent_id`, `size` and **raw-byte**
`sha256`. `put` validates the write response, which is not read-back evidence.
`verify_readback` independently calls `stat` and `get`, checks every metadata
field and exact byte equality, and optionally checks the index's `LF_UTF8_v1`
hash. BOM/line-ending normalization must not conceal changed stored bytes.
A provider without a hash must calculate it from a complete read, not invent it.
Transport reads must not serve a cached copy of the submitted write.

```python
from skytale.storage import ObjectStoreAdapter, verify_readback
from skytale.core import sha256_lf_utf8_v1

# authorized_client is supplied by the operator, never by repository secrets.
store = ObjectStoreAdapter(authorized_client, store_id)
meta = store.put(file_name, original_bytes)
evidence = verify_readback(
    store, meta, original_bytes,
    normalized_sha256=sha256_lf_utf8_v1(original_bytes),
)
```

The result establishes only this read-back route. A mock/local transport does
not become remote evidence by calling the same function. Listing is discovery,
not a way to infer the latest generation: always read the committed pointer.
No pointer write, CAS, multi-file transaction or automatic state promotion is
implemented here. Keep the previous pointer on any verification failure.

## Events: read schema, validate options, read all six columns

Implement `EventStoreClient` against the **existing** event store. It must map
provider-specific columns into the logical `EventSchema` types:

| Column | Logical type |
| --- | --- |
| name | text |
| owner | select |
| state | select |
| time | timestamp |
| note | json |
| source | url |

`read_schema` must return current owner/state options, not hardcoded defaults.
The adapter never creates an option, database or schema. The note is a JSON
object with `action`, `handoff_id`, `request_id`, and `reason`; a transport maps
it to/from its provider's text/structured representation without losing fields.
`source` is the HTTP(S) link to the index, not merely an index id.

```python
from skytale.events import EventStoreAdapter, EventIntent

intent = EventIntent(
    agent=agent_name, generation=generation_id, action="check_out",
    owner=existing_owner_option, state=existing_state_option,
    occurred_at=actual_event_time, source=index_link, reason=trigger_reason,
)
evidence = EventStoreAdapter(authorized_event_client).ensure(intent)
```

`ensure` always reads schema first, validates existing options and a real,
timezone-aware timestamp (not future or before the generation), then searches
by the exact generated request id. One existing match is independently read and
verified; multiple matches fail. A new row is read back, all six columns are
compared, then the search is repeated to detect observed concurrent duplicates.
A timeout or missing column never returns successful evidence. A retry must use
the same full intent, including original event time. Changed content requires a
new generation. Search must include **all pages**; an eventually consistent or
incomplete read may fail and must not be promoted to a commit.

`verify(event_id, intent)` reads an existing check-out without creating anything.
Use it before a new session creates its own check-in via `ensure` with action
`check_in`. The library does not establish session identity or prove semantic
recovery: the caller must enforce the startup/close authorization boundary.
The old session must never submit the new session's check-in.

**Concurrency limit:** search/create/read is not atomic. The second search can
detect some races, not prevent all future duplicates. `atomic_claim=False` is
explicit. Use a provider uniqueness constraint or separate coordinator if a
single-writer guarantee is needed; this adapter makes no lock/CAS claim.

## Dispatcher: a separate receipt route

`DispatcherAdapter(client).readback(DispatchRequest(agent, request_id, source))`
fetches a dispatcher receipt through an injected `read_receipt` transport.
`verify_receipt` accepts only exact agent/request_id/source matches and
`status == "PROCESSED"`. Missing, pending, accepted, failed and lower-case status
values fail. Provider transports must map their documented status field to this
logical payload; never manufacture a receipt from a direct event API write.

A successful receipt proves only dispatcher processing, not SDK wake, chat
arrival, context reading, recovery, check-in or completed handoff. Receipt
provenance depends on the injected client; a locally supplied dictionary alone
is not independent dispatcher evidence.

## Acceptance boundary

Run from `skytale/`:

```bash
python -m unittest discover -s tests -v
python -m skytale.cli check --dir examples/demo
python -m skytale.cli prompt --dir examples/demo
```

Contract tests use explicitly synthetic in-memory transports. They cover raw
and normalized hashes, truncated/mutated content, metadata/parent mismatch,
schema/options, every event read-back column, retries, wrong generations,
observed duplicates, invalid/future times, and receipt identity/status.

Live acceptance is still required: authorized provider transport wiring,
independent storage reads, schema and six-column event reads from the existing
store, and a real dispatcher receipt. No new conversation recovery, remote
commit, live receipt, delivery or completed handoff is claimed by these tests.
