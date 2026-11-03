# Architecture

Signed channel event -> canonical workspace event -> SQLite event/job transaction -> leased worker -> knowledge rules or OpenAI-compatible generation -> policy/review -> durable outbox -> channel adapter -> provider acknowledgement -> audit/dashboard.

Core business flow is independent of customer and channel. Workspaces own their knowledge/policy; adapters own signature verification, normalization and delivery. No credentials are exposed by management APIs.

States: queued -> review/pending_send -> simulated/sent/failed/unknown. Review can be approved or rejected. Unknown sends are not automatically retried. Incoming events commit before acknowledgement; unique(workspace, channel, external_id) handles redelivery. This is not platform-wide exactly-once delivery.

Native Meta/LINE adapters and a clearly separate approved TikTok connector interface are included. Historical-post import and unauthorized account crawling are excluded. Model and channel services are fixtures in the local E2E suite. Traditional-Chinese UI and fictional test utterances are intentional multilingual product assets.
