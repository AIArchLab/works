# Approved TikTok Business connector contract

This is an explicit integration boundary, not a claim of native TikTok webhook/API access. The authorized upstream native partner connector is not included.

## Inbound
POST `/webhooks/{workspace}/tiktok`, JSON:
```json
{"events":[{"id":"unique-event-id","comment_id":"owned-comment-id","text":"Example question"}]}
```
`X-Connector-Signature`: hex HMAC-SHA256 of exact raw body using the connector secret. This is this product's contract, not TikTok's native signature format. Upstream must validate real platform signatures, account ownership and authorization before normalization.

## Outbound
POST to `TIKTOK_CONNECTOR_URL`:
```json
{"event_id":"upstream-event-id","comment_id":"comment-id","text":"Reply","workspace":"demo"}
```
Same raw-body HMAC and internal event ID as `Idempotency-Key`. Connector must enforce workspace/account authorization and durable idempotency, call its approved upstream API, then return HTTP 200 with `{"id":"provider-reply-id"}` only after acceptance. A clear 429 can be retried. Ambiguous transport or 5xx enters unknown; do not blindly resend.
