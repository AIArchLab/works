# AIArchLab visual introduction

Date: 2026-11-04 (Asia/Taipei)
Brand and editorial composition: AIArchLab.
Content baseline: fe5dd8aa3e0a57ab9e05c9cbcb75e2da59764d43. This is a visual explanation of v0.1.0, not an independent acceptance report for later source changes.

## Assets and limits

- task-continuity-concept.png: conceptual visualization of the Python / Broker / Node reference flow, not a recording. Save, PREPARED, CLAIMED and ACK are distinct. UI demo combines claim, verify and ACK.
- task-continuity-ui-excerpts.mp4: 21-second edited excerpts of actual local UI states, not continuous capture. Receiver is Python, not Node. Stop/restart actions occur off screen; the frames show a failed request followed by the same task's restored PREPARED state, receiver epoch 2, stale-lease write rejection, and unchanged receiver state.
- poster.png: frame from the edited UI video at 15 seconds.

Fencing covers Broker-mediated state and artifacts, not arbitrary external side effects. ACK is not task completion. Single-node developer / controlled-pilot scope. No claim of all-runtime support, SaaS readiness, or fresh independent test pass. Synthetic task identifiers; no credentials shown.

## Reproduction

The source directory contains the approved UI excerpts input, graphic composition, caption filter and rebuild script. Run `sh rebuild.sh` there. Requires Python 3, Pillow, DejaVu Sans, FFmpeg with libx264 and drawtext. DejaVu fonts are used under their installed font license; no external photography or brand logos are embedded.

Video: H.264, yuv420p, 980x1080. The composition adds captions outside the UI; original UI state sequence is retained.

## SHA-256

- `poster.png`: `64d00bee6a42298bcbd841ca2d6eadf55296b0c1c56c578c0b89cea5743e549c`
- `source/aiarchlab-intro-20261104/captions.ffscript`: `ec9d71f3e09d07d58009a09f0a369363bfdc2421140bf665cd694c428d5a1c67`
- `source/aiarchlab-intro-20261104/draw_concept.py`: `65ffffccf0c915f4b05039d594d33ffe5caaa6a9cf34e3f954f301e5bbab2c25`
- `source/aiarchlab-intro-20261104/rebuild.sh`: `77216548b42a53d30380cfe3838e401a304fa7ba1c973b272c7125aa81ea6e8c`
- `source/aiarchlab-intro-20261104/ui-excerpts-source.mp4`: `5abcdeef7d063ad93163f820079235e1ef47fd3e41208bcc6485e336173bb4d1`
- `source/aiarchlab-intro-20261104/video-bg.png`: `2b1a54035a974bfb6360c161661f51f062253515942e612c9d022cfc26112c8a`
- `task-continuity-concept.png`: `19e56661f3732ee152f528c036d14929c6c99893e3bad3c5637be45a22202202`
- `task-continuity-ui-excerpts.mp4`: `55a6580c5ba2b88a4b7badfd57029915abfa279e2ae4871c4e2c0464708e27ac`
