# SocialReply

**Status:** Sanitized Example. Runnable multi-workspace social reply MVP.
**Evidence state:** Local HTTP end-to-end tests passed; real model inference and live social accounts have not been verified. Scenario and data are fictional.

## Run
Python 3.10+, standard library only. No dependency installation.

```sh
python3 app.py --open
```
Windows: run `run_local.bat`. macOS/Linux: `sh run_local.sh`.
The launcher creates a local admin credential and opens the dashboard. The UI and fictional customer messages are in Traditional Chinese.

Choose the four-channel demo to exercise receipt, persistence, reply selection, policy checks, outbox, simulated delivery, and audit. Default operation is explicitly **knowledge rules plus simulated channels**, not real LLM inference or live social delivery.

## Reusable product core
- Workspace-specific knowledge and reply policies, shared durable worker and outbox.
- Native Meta comment and LINE text-message adapters.
- Explicit approved TikTok Business connector interface, not a fabricated native API.
- OpenAI-compatible HTTP client with structured-output, source-ID and confidence checks.
- Review queue, approval/rejection, audit trail, signed webhooks and redelivery deduplication.
- Uncertain sends stop automatic retries; completed demo deliveries survive service restart.

## Tests
```sh
python3 -m unittest discover -s tests -v
```
See `ACCEPTANCE.md` and `test_report.json`. The test suite starts actual local HTTP services and exercises the complete application boundary. External model and channel services are clearly identified fixtures, not real providers.

## Connect authorized accounts
Copy `.env.example` to `.env`; configure model and authorized platform credentials once. Do not commit secrets. Credentials are read from environment variables, with per-workspace prefixes.

Configure public HTTPS callbacks:
- LINE: `/webhooks/demo/line`
- Instagram/Facebook: `/webhooks/demo/meta`
- Approved TikTok connector: `/webhooks/demo/tiktok`

Set `APP_MODE=live` only after platform authorization and subscription. Live events still require review unless `LIVE_AUTO_SEND=1` is explicitly configured. The simulation endpoint never posts to a real account. Configure the actual authorized Graph version rather than guessing it.

TikTok requires a separately authorized Business connector; see `CONNECTOR_CONTRACT.md`. This native partner connector is not included. LINE uses reply only, with an application-defined conservative 45-second guard; there is no automatic paid push fallback.

## Limits
Single owner-admin, not customer-facing RBAC SaaS. Use a trusted network or authenticated TLS reverse proxy. Use one application instance with SQLite. Provider acceptance is not user delivery/read confirmation. Knowledge rules and source-ID checks do not prove semantic correctness or eliminate prompt injection. Short-lived LINE reply tokens may be held in the restricted local database until delivery. Add retention and field encryption where required.

Docker configuration is supplied but has not been executed in the build environment. No real-browser click test, real model inference, real platform delivery or production deployment is claimed.

## API references
- https://developers.line.biz/en/reference/messaging-api/#send-reply-message
- https://developers.facebook.com/documentation/instagram-platform/comment-moderation
- https://business-api.tiktok.com/portal/docs/reply-to-an-existing-comment-on-an-owned-video/v1.3

References checked 2026-11-03. Platform and account permissions still require live verification.
