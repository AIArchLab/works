# Changelog

## v2.1.6-generic — 2026-10-22

Generic rewrite of the check-in SDK.

- Removed all embedded database ids, property names, user paths, credentials,
  organization names, and internal URLs.
- Required configuration is now environment/CLI based.
- Property mapping is configurable (`CHECKIN_PROP_*`).
- Timezone offset is configurable (`CHECKIN_TZ_OFFSET`; default `+00:00`).
- No default Notion database id.
- No credential file fallback.
- Idempotency failure now fails closed.
- Python-only reference implementation.
