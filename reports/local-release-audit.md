# Local Release Audit

- Audited at: 2026-08-12
- Skill version: 0.7.1
- Phase: local
- Publication requested: no

## Passed

- Package validation: pass, zero warnings.
- Trigger eval: 16/16.
- Direct Windows unit tests with `python`: 23/23.
- Real-project continuous tracking: 96.83% two-hand coverage with 10 line frames, 9 opening frames, 42 open frames, 1 held frame and 1 absent frame.
- Real-project reveal grows from mean source delta 0.1218 at 1.5s line phase to 0.5610 at 2.5s opening, 1.0327 at 3.5s and 4.7707 at 3.6667s.
- Aligned mask-window regression: overlay pixels retain their full-frame positions inside the hand polygon; perspective mode is rejected; legacy perspective configs migrate to clip.
- Real in-app Chromium drag test: portrait canvas visible box matches 9:16 source; a white corner handle and the quadrilateral followed the pointer; test displacement was reset afterward.
- Real-source integer preparation: 10.000-second video stream, 300 frames, 1080×1920, 30 fps; source file remained unchanged.
- Named-IP compatibility aliases resolve to original archetypes, and generated Provider instructions exclude named-IP tokens.
- Recorded fixture: pass for transform request, no-gender-inference contract, automatic media QA, rejected unapproved transform, hand-frame confirmation, render and verification.
- 0.4.0 recorded fixture: pass for request, automatic media QA, rejected unapproved transform, review confirmation, render and verification.
- Secret scan and source immutability checks: pass in local release tooling.

## Expected local-only blockers

- Package directory is not an independent Git repository.
- No feature branch or remote release exists.
- The meta release checker may invoke `python3`, which is not configured on this Windows host; direct PowerShell/Python validation remains the authoritative local Windows result.

These block a “published/release ready” claim, not local package use.

## Missing evidence

- The manual Seedance result has no task ID, generation-page screenshot or credits record, so the model/provider claim remains user-reported rather than provider-backed evidence.
- The current real project has non-blind user browser confirmation; there is no independent or blind reviewer evidence.
- Commercial rights, cross-project real-person temporal consistency, fast/occluded hand tracking, 4K/HDR/VFR/long-video behavior and cross-platform installation remain unverified.
