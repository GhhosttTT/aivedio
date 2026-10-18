# Seedance-level capability target

This project can approach the user experience of a commercial multimodal video
model, but a local SDXL/SVD stack cannot reproduce the foundation model itself.
The practical target is a provider-neutral production system with the same
control surface and stronger deterministic quality gates.

## Capability contract

External video providers receive a single request containing:

- text direction and negative constraints;
- multiple image, video, and audio references;
- optional continuation clip and end frame;
- a shot plan, multi-shot flag, and native-audio preference;
- duration, aspect ratio, seed, and motion controls.

The legacy `reference_image` field remains supported for ComfyUI and SVD.
External gateways can consume the richer `references` array directly or map it
to their own `@Image1`, `@Video1`, and `@Audio1` syntax.

For Volcano Ark, set `SEEDANCE_API_FORMAT=ark_v3`. The adapter emits the native
`content[]` request with explicit media roles, uses `ratio` instead of the
legacy `aspect_ratio`, and maps model-selected duration to `-1`. A configured
2.5 model automatically gets the 30-image/10-video/10-audio limits unless the
operator explicitly overrides them.
Native Ark prompt bindings use the official lowercase `@image1`, `@video1`, and
`@audio1` labels; generic legacy gateways retain their historical capitalized
labels.
The native `omni_reference_task_type` hint is emitted only for Seedance 2.5;
Seedance 2.0 and 1.0 rely on their respective prompt/content contracts and do
not receive this 2.5-only field.
The adapter also enforces the native 2.5 aggregate limit of 50 reference
items, including an end-frame image when it is not already listed.

When `SEEDANCE_REQUEST_MODE=multi_shot`, the default task mode keeps each atomic
scene at its director-planned duration while sending bounded previous/current/
next continuity context. This prevents a project with many scenes from
accidentally generating a separate 30-second clip for every scene. An explicit
`SEEDANCE_SEQUENCE_LEVEL_MULTI_SHOT=true` sends the project-level timestamped
`shots` plan and requests the configured 15/30-second sequence duration. The
generated sequence is then split into atomic scene files using the same timeline
contract that drives dialogue and subtitles, so a multi-scene project does not
accidentally multiply 30-second jobs. This mode remains opt-in until real Ark
samples validate shot-boundary quality.
The native Ark preflight rejects a sequence duration outside the selected
model's contract (4–15 seconds for Seedance 2.0, 4–30 seconds for Seedance
2.5) instead of allowing the provider to clamp it and silently desynchronize
the local timeline.

After splitting, every atomic scene now receives its own technical metrics and
final review before publication; a sequence-level pass for the first shot can no
longer implicitly approve all of the derived shots.

Set `GENERATION_PROVIDER=seedance_api` to use the explicit adapter. It emits
the separate `image_urls`, `video_urls`, and `audio_urls` fields expected by
reference-to-video gateways, while preserving the existing async polling and
artifact validation behavior.
The workbench can override `SEEDANCE_MODEL` for one production run without
mutating process configuration. The selected model is included in the pending
task fingerprint, so resuming a task created for a different model is rejected
instead of attaching the wrong remote job to the output path.
The native adapter requests the documented `return_last_frame` field for Ark
continuity and falls back to local ffmpeg extraction when a gateway does not
return a usable frame URL. Seedance 2.5 Draft mode is exposed as a 480p
preview option and can be promoted with the returned `draft_task_id`. Draft
promotion uses the native two-step contract: it sends `1080p` plus output
controls and does not resend prompt, references, duration, ratio, seed, audio,
or task type. Native 2.5 first/last-frame requests default to the configured
production resolution (1080p by default) while honoring an explicit 480p/720p
choice; the provider rejects Draft combined with first/last-frame mode before
spending a request.
Draft generation and promotion are rejected before submission for native
Seedance models other than 2.5, matching the model capability boundary instead
of allowing a paid request to fail remotely.

Cancellation is also provider-aware: cancelling an in-flight task stops local
polling and generation fallback, and attempts Ark's `DELETE` task operation
when the remote task is still queued. Ark rejects cancellation after a task
enters `running`, so a successful local cancellation remains the authoritative
user-visible state in that case.

Native Ark callbacks are accepted at `/api/webhooks/seedance` with an optional
shared secret. Matching terminal callback payloads are written next to the
pending sidecar and consumed before the next status poll; polling remains the
fallback when a webhook is delayed or unavailable.

If a remote task has already been accepted but its status becomes ambiguous,
the task runner will not create a second draft fallback job. This avoids
duplicate provider charges and preserves the pending task sidecar for recovery.
The sidecar also stores a request fingerprint, so reusing an output path with
different prompt, references, or timing controls is rejected instead of
silently attaching the old remote task to a new shot.
The sidecar now also stores the provider controls for that accepted request.
Retrying a failed production task with a consistent pending sidecar resumes
only the video stage with the original model/mode/resolution/audio settings,
preserving the image and audio inputs needed for fingerprint validation rather
than rebuilding the whole paid request.
Sequence-level multi-shot sidecars are retained during split/review cleanup and
carry their original sequence output path, so a failed 30-second request can
resume the same remote task before the atomic scene files are republished.
Each sidecar is bound to the local production task that created it; retries
ignore stale sidecars left by older runs in the same project directory.

The legacy reference limits are Seedance 2.0-compatible (9 images, 3 videos,
3 audio clips). For legacy gateways, raise the three
`SEEDANCE_MAX_REFERENCE_*` settings manually when the gateway exposes 2.5.

Production preflight distinguishes native Ark image transport from local
video/audio transport: images may be sent as Base64, while edit/extend jobs
using local video or audio require `SEEDANCE_MEDIA_URL_TEMPLATE` or pre-ingested
public asset IDs. Edit/extend mode is blocked before task reservation when that
transport is missing; ordinary image-reference mode reports it as a warning.

The gateway smoke command now validates live output artifacts after download:
it rejects unreadable files, invalid geometry or duration, missing requested
audio, and unusable decoded audio signal. This keeps a successful provider
poll from being mistaken for a publishable video.

Native Ark preflight now also follows the model-specific multimodal contract:
Seedance 1.0 is routed through the explicit first-frame/first-last-frame
contract (Pro Fast does not support first-last-frame) and does not advertise
full-modal references. The task builder also strips automatic previous-shot
video, dialogue-audio, continuity-image, and character-sheet references for
Seedance 1.0, so a multi-scene project cannot accidentally submit a 2.x
omni-reference payload to the 1.0 endpoint. Seedance 2.0 accepts
reference audio only when at least one image or video is also supplied and is
capped at 15 total references; Seedance 2.5 allows the larger
30-image/10-video/10-audio, 50-item contract. Invalid combinations fail before
a paid task is submitted. Resolution and duration are also model-specific:
Seedance 2.0 Fast/Mini are limited to 480p/720p, Seedance 2.0 supports 4K,
and Seedance 1.0 uses a 2–12 second duration contract. Seedance 2.0 generated
outputs use the current 4–15 second contract; ordinary Seedance 2.5 tasks
accept 2-second clips, while native 2.5 edit/extend tasks require at
least 4 seconds and use automatic duration (`-1`) for the output.

## Quality bar

The next production milestone is measured on real samples, not unit tests:

1. two-character identity retention across five shots;
2. camera/action continuity across shot boundaries;
3. dialogue-to-mouth/action timing and audio continuity;
4. no static/frozen candidates, malformed hands, or unintended characters;
5. human review of a complete 30-second sequence.

The final-composition reviewer now receives bounded `sequence_contexts` for
every shot, so its episode continuity rubric can compare adjacent shots instead
of seeing only an undifferentiated list of scene descriptions. Failing
screen-direction, position, prop, or cut-smoothness evidence is routed through
the existing spatial/video repair queue.

Sampled-frame review is also time-distributed across the whole clip. Each
three-frame VLM window carries one adjacent context frame at its boundaries;
that context is not scored twice, but exposes identity, wardrobe, and camera
discontinuities that would otherwise fall between independent review windows.

Sequence-level multi-shot requests additionally bind every approved
character-sheet reference to its exact `@ImageN` index, including references
collected from later scenes, so a long request does not leave role identity to
implicit image ordering.

The deterministic acceptance layer also rejects mismatched geometry at shot
boundaries, missing or unmeasurable expected audio duration, audio/video
duration drift above 0.35 seconds, and obvious drift from a locked opening
keyframe. It also measures near-black frame runs and rejects black-screen
artifacts longer than the configured 0.2 seconds. These checks are intentionally
separate from the VLM review: a model score cannot override a malformed
timeline or an unverifiable audio contract.

When native audio is requested, technical metrics now inspect the decoded audio
signal as well as stream presence and duration. Near-silent or unmeasurable
audio is rejected as a production candidate instead of passing merely because
the container contains an audio track. Reference audio is treated as an output
contract too, and normalization preserves it even when native audio generation
is disabled.

The same decoded-signal gate is applied again after full-episode composition;
an AAC stream that exists but contains silence cannot bypass the final publish
check. This prevents a scene-level pass from being undone by concat or muxing.

The final technical gate also rejects a genuinely frozen low-motion run longer
than `GENERATION_VIDEO_MAX_STATIC_RUN_SECONDS`; this is conditional on very low
motion energy so intentional slow reaction beats are not treated as defects.

The local baseline comparator applies a stricter shot-level check as well: its
report records `max_static_run_seconds` and fails candidates with a prolonged
sampled freeze even when their aggregate motion score is otherwise acceptable.
This makes real Seedance sample comparisons useful for catching mid-shot
stalls, not just completely static outputs.

The comparator also hard-gates prolonged black frames, temporal exposure jumps,
and unstable motion cadence, so a playable but visibly broken Ark artifact is
not accepted as a baseline match.

Native Seedance 1080p/4K outputs also carry codec, pixel-format, and bit-depth
metadata through the provider and normalization reports. If a native Seedance
high-resolution clip is reduced to 8-bit during post-processing, final
acceptance rejects it instead of silently publishing a lower-fidelity result.
Native Seedance 2.5 1080p responses are also rejected immediately when the
provider returns anything other than 10-bit HEVC, matching the model's native
output contract before normalization can hide the downgrade.

Without a real multimodal video endpoint and licensed model assets, the local
provider should be presented as a draft/repair engine rather than as Seedance
parity.
