# Demo video: repository collaboration board

Request: GPAI-SOCIALREPLY-DEMO-20261103-01
Working directory: socialreply/demo/
Coordination date: 2026-11-03

The Founder directed collaborators to work directly in this repo. Commit assets, reviews and status updates here. Do not use Notion as a second progress board or make the Founder transfer files. Existing Notion tasks are only legacy routing/evidence references.

## Owners and actual state

| Work | Collaborator | Current evidence | Next repo deliverable |
|---|---|---|---|
| Product/source support and final acceptance | GPAI | Source and recording request are committed | Validate delivered video and record result |
| Actual browser recording | dsh-sd (invited) | No recording acceptance or footage observed in the last task-comment check | Commit acceptance or a concrete blocker; then footage plus provenance |
| Storyboard, Traditional-Chinese subtitles and editing | Instinct | Accepted in the legacy task comment; reported storyboard/subtitle drafts ready. Files not yet received in this repo | Commit actual storyboard and SRT, then edit recorded footage |

Acceptance by comment is not delivery. A script is not video. A reported draft is not a received file. Collaborators should replace these rows with their own commit-backed updates, not claim another member has accepted.

## Commit the actual artifacts

- `storyboard.md`: actual shot list and editing decisions.
- `captions.zh-TW.srt`: actual captions, retimed to real footage.
- `raw/`: raw MP4 if small enough, otherwise `raw/ASSET.json` with a stable authorized download URL, SHA-256, duration and provenance. Never include real credentials or local admin tokens.
- `socialreply-demo.mp4`: final video, preferably under 20 MB; otherwise stable video URL plus hash in `DELIVERY.json`.
- `REVIEW.md`: reviewer, reviewed commit/video hash, decoding/playback check and actual remaining defects.

Do not create placeholder media or mark it delivered because a path is listed. Do not overwrite another collaborator's assets without the Founder's approval; use a new version or branch when revising their deliverable.

## Minimal repository workflow

1. Pull latest main and inspect REQUEST.md and this board.
2. Commit your own acceptance or blocker here. Use a focused branch/PR if available, or your authorized direct-push route.
3. Commit the actual source materials and record their hashes. Keep changes within socialreply/demo/ unless fixing an actual source defect.
4. Pull/rebase before pushing; preserve other contributors' work.
5. The next collaborator reads committed files directly; no manual message relay is required from the Founder.
6. GPAI checks the final media, then records acceptance. No unobserved delivery or background monitoring is claimed.

## Legacy acceptance source

Instinct task comment: https://app.notion.com/p/40d3895ec71181159c60e42dcd2a6ec9
Reported: accepted storyboard/subtitles/editing; drafts ready; awaiting actual recording. This historical report does not establish that assets have been committed.
Recording invitation: https://app.notion.com/p/40d3895ec711811bbac1fb743c488622

## Video boundary

Actual app footage; visible demo/knowledge-rules/simulated-channel status; fictional data only. No claim of live model inference, native TikTok partner integration or real-platform delivery. Full recording specification: REQUEST.md.
