# AI Short Drama Platform Gap Analysis

Date: 2026-09-20

This document compares the current local-first platform with production patterns
used by stronger AI short-drama workflows. The goal is to define what must be
controlled by the product pipeline before local ComfyUI, llama.cpp review, ASR,
translation, subtitles, and composition can reliably produce high-quality
short-drama output.

## Reference Production Chain

Current public short-drama generation research and commercial tools converge on
the same production pattern:

1. Story planning
   - Validate genre, target audience, emotional hook, conflict, reversal, and
     ending before generation.
   - Use reviewer loops to reject weak pacing, unclear motivation, and scenes
     that cannot be filmed.

2. Character bible
   - Generate each character as a reusable asset, not as prompt text only.
   - Store face, body, outfit, age range, hairstyle, voice tone, and negative
     identity constraints.
   - Use reference images or identity embeddings during image and video
     generation.

3. Scene and shot decomposition
   - Split the script into atomic shots. Each shot should carry one visible
     action, one camera intention, and one emotional beat.
   - Keep short-drama rhythm tight: hook early, escalation every few shots, and
     clear cliffhanger or payoff.

4. Spatial and camera planning
   - Track where characters stand, where props are, camera angle, shot scale,
     depth, and pose.
   - Stronger systems retrieve or build depth/pose/camera references before
     first-frame and image-to-video generation.

5. First-frame generation
   - Generate multiple candidate keyframes per shot.
   - Score each image for story match, composition, visual integrity, character
     identity, beauty, and production usability.
   - Keep rejected candidates as evidence for refinement prompts.

6. Motion generation
   - Use image-to-video with the accepted first frame, director prompt, negative
     prompt, and optional last frame.
   - Prefer workflows that support reference images, motion control, first-last
     frame, native audio or later lip sync.

7. Multi-stage review and retry
   - Review script, images, video frames, temporal consistency, identity drift,
     prop continuity, subtitles, audio sync, and final composition.
   - Failed clips should enter a repair queue with targeted reasons.

8. Post-production
   - Compose accepted clips, normalize audio, render subtitles, add BGM,
     transitions, cover, metadata, and platform-specific export presets.

9. Localization and publishing
   - ASR or script-aligned dialogue extraction.
   - Local translation into target languages.
   - Subtitle rendering, dub or voice cloning when available, final review per
     language, and export packages.

10. Feedback loop
    - Store human decisions, accepted/rejected candidates, scoring reports, and
      final audience metrics.
    - Feed winning patterns back into prompt templates, scene splitting, and
      generation settings.

## Practical Platform Production Chain

A production short-drama platform usually behaves like a small content factory:

1. Topic and market selection
   - Pick genre, audience, region, platform ratio, runtime, risk words, and
     commercial style before writing the first script.
   - Strong teams track which hooks, identities, conflicts, and endings convert.

2. Story room
   - Produce logline, episode arc, character conflict, beat sheet, scene list,
     dialogue draft, rewrite notes, and final locked script.
   - Weak scripts are rejected before visual generation to avoid wasting GPU
     time.

3. Asset bible
   - Lock character faces, body shape, wardrobe, props, locations, voice tone,
     negative identity constraints, and sample references.
   - Reuse these assets across every shot and episode.

4. Director plan
   - Convert script into atomic shots with shot scale, camera angle, action,
     expression, emotional beat, visible characters, prop focus, and continuity
     notes.
   - Generate pose, depth, camera, and first/last-frame references when needed.

5. Batch candidate generation
   - Generate multiple first-frame candidates per shot, score all candidates,
     keep evidence, and only send approved frames into video generation.
   - Video generation repeats the same pattern: multiple candidates, review,
     repair, then acceptance.

6. Post-production
   - Assemble accepted clips, align dialogue, normalize loudness, add BGM,
     render subtitles, add cover/title cards, export vertical presets, and keep
     source packages for reuse.

7. QA and publishing
   - Review story rhythm, identity, motion, image defects, audio sync, subtitle
     readability, platform rules, and final watchability.
   - Store human decisions and audience feedback as data for the next batch.

## Current System Coverage

Already implemented or partially implemented:

- Local-first architecture with ComfyUI and llama.cpp reviewer support.
- Script generation with a 16-scene production target.
- Character services, reference generation, identity scoring, and visual anchor
  payloads.
- Character asset-pack freezing stores the approved identity bible and reference
  image hashes so production readiness can detect stale character assets.
- Shot prompt compiler and complexity checks for overloaded scenes.
- Director-led video shot plans with duration, motion, prompt, negative prompt,
  end-frame prompt, and candidate reports.
- Project-level spatial asset packs can freeze shot scale, camera angle, camera
  axis, character positions, prop focus, and pose/depth/camera control prompts
  before rendering.
- Multiple image and video candidates with quality review hooks.
- Production video engine preflight and draft fallback separation.
- ASR, local translation, subtitle rendering, localization quality checks, and
  source-video localization modules.
- Seed Dance baseline comparison script and production validation summary.
- Production readiness reports surface script, rhythm, visual format,
  story-room quality, character, shot complexity, spatial continuity, reviewer,
  video-engine, and sample-validation status.

## Major Gaps

1. Story room quality is still shallow
   - The system can generate scripts, but it does not yet enforce hook,
     escalation, reversal, payoff, and episode rhythm as first-class gates.
   - Needed: a structured story-review contract with short-drama-specific
     metrics and automatic rewrite attempts.

2. Market and topic selection are missing
   - The current system starts from a user idea, but strong platforms treat
     topic, audience, genre, region, hook type, and platform policy as inputs.
   - Needed: a topic brief, comparable-hit library, risk checklist, and scoring
     model before script generation.

3. Character bible is not strong enough
   - Character references exist, but the platform still needs a required
     character bible before production.
   - Needed: face/body/outfit/voice/personality assets, per-character negative
     prompts, approved reference sets, and per-shot visible-character mapping.

4. Spatial continuity is weak
   - The current planner does not maintain a reusable stage map, character
     positions, prop positions, camera axis, pose/depth references, or room
     layout.
   - Needed: a `spatial_plan` per scene and shot, plus reference retrieval or
     generated control images for depth, pose, and camera composition.

5. Generation workflow depends on installed ComfyUI graph quality
   - The backend supports prompt-aware ComfyUI workflows, but production quality
     still depends on the actual graph and models installed on the machine.
   - Needed: pinned workflow profiles for high-quality portrait image,
     first-last-frame video, face consistency, hand repair, upscale, and
     flicker reduction.

6. Review is evidence-bearing but not yet full repair automation
   - The reviewer can score outputs, but rejected clips need a more complete
     retry planner that chooses whether to rewrite prompt, regenerate reference,
     lower motion, split shot, or change camera.
   - Manual review must cover every rendered validation case. The validation
     summary now blocks readiness when only a subset of generated cases has
     human scores.

7. Final editing intelligence is basic
   - Composition exists, but there is limited logic for short-drama rhythm,
     reaction shots, transitions, beat timing, audio ducking, BGM matching, and
     cliffhanger packaging.

8. Platform UI should expose production readiness
   - The backend can block some invalid production attempts, but the UI should
     show a readiness checklist before users click production.
   - Needed: script readiness, character readiness, engine readiness, review
     readiness, localization readiness, and missing-action buttons.

## Gap To Strong Short-Drama Platforms

The biggest gap is the amount of controlled evidence before each render. Strong
platforms do not rely on one prompt to produce a finished shot. They lock a
story decision, character assets, spatial plan, camera intent, first frame,
motion candidate, review result, and repair history for every shot.

Current system advantages:

- Local-first architecture already fits the user's hardware and privacy
  requirement.
- The generation provider abstraction can swap ComfyUI workflows without
  replacing the business pipeline.
- Readiness and sample validation prevent unit tests from being mistaken for
  visual quality proof.

Current system gaps before it can be treated as a production platform:

- No topic library or market scoring loop.
- No required story-room approval gate before generation.
- Character bible exists technically, but still needs a UI workflow for
  approving and freezing character packs.
- Spatial planning is generated on demand, but not yet persisted as a first
  class production asset with pose/depth/control references.
- ComfyUI workflow quality is still external to the repo and must be pinned on
  the target GPU.
- Repair automation is partial; failed clips need automatic retry decisions and
  budget limits.
- Final edit intelligence is still basic compared with human editors or mature
  platforms.
- Real sample acceptance remains required. Passing tests prove contract
  behavior, not Seed Dance-level visual quality.

## Immediate Implementation Direction

Priority 1: Stop bad projects before generation.

- Production should require at least 16 atomic scenes when video generation is
  enabled and draft fallback is disabled.
- This keeps quick draft mode available while preventing underplanned scripts
  from being treated as final short-drama production.
- Current implementation also reports `story_room` quality in production
  readiness. It checks topic/market brief, early hook, dialogue or reaction
  drive, escalation cadence, reversal, ending hook, emotional progression, and
  overloaded non-atomic shots before expensive rendering starts.

Priority 2: Add a production readiness report endpoint.

- Return all blockers in one response:
  - scene count
  - overloaded scenes
  - missing character references
  - production video engine status
  - local reviewer status
  - localization model status
- Current implementation exposes `GET /api/projects/{project_id}/production-readiness`.
  The response separates `blockers` from `warnings` and includes `checks` for
  script structure, character assets, shot complexity, local reviewer settings,
  and optional video-engine preflight. The frontend should show this before the
  user starts final production.

Priority 3: Add character bible enforcement.

- Each visible character must have approved reference images and distinct face,
  body, outfit, and negative identity anchors.
- Multi-character scenes must pass distinctness checks before production.
- Current implementation can freeze a character asset pack with
  `POST /api/projects/{project_id}/characters/{character_id}/freeze-asset-pack`.
  The pack records the identity-spec hash and reference-image hashes. If either
  changes, production readiness blocks final generation until the pack is
  re-frozen.

Priority 4: Add spatial planning.

- Store room layout, camera angle, shot scale, character position, prop
  position, and pose/depth/control references.
- Use this data in image and video prompts.
- Current implementation can freeze the project spatial plan with
  `POST /api/projects/{project_id}/freeze-spatial-plan`. Production readiness
  blocks final generation when the pack is missing or stale after script,
  dialogue, visible-character, or spatial-plan changes.

Priority 5: Add repair queue.

- Convert review failures into targeted repair tasks.
- Keep evidence for every accepted and rejected candidate.
- Current implementation writes `repair_queue` into failed or review-unavailable
  image/video `.quality.json` reports. The queue maps evidence such as identity
  drift, bad crop, prop issues, temporal flicker, camera jumps, complex shots,
  and missing local VLM review into targeted repair actions.

## Sources Used For Benchmarking

- One Sentence, One Drama: Personalized Short-Form Drama Generation via
  Multi-Agent Systems, arXiv 2605.22144.
- DramaDirector: Geometry-Guided Short Drama Generation, arXiv 2606.24107.
- Kling AI 3.0 public product page, especially multimodal storyboard,
  identity, sound, and consistency claims.
- InstantID: Zero-shot Identity-Preserving Generation in Seconds, arXiv
  2401.07519.
- RunComfy ComfyUI workflow catalog for IPAdapter, ControlNet, AnimateDiff,
  SVD, face consistency, inpainting, and upscaling workflow families.
