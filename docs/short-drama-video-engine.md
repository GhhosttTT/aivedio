# Short-Drama Video Engine

The platform should not treat Stable Video Diffusion as the production product.
SVD is a local fallback engine. The product layer is a director-led video
pipeline that can use ComfyUI/Wan/AnimateDiff, an external API, or SVD behind the
same contract.

## Current Engine Contract

For every atomic scene, the video stage now builds a `VideoShotPlan` before
calling the model:

- shot role: action, prop interaction, emotion reaction, dialogue reaction, or establishing
- target duration: based on dialogue length and short-drama pacing
- model frames/fps: bounded by project settings
- motion strength and noise: tuned by shot role
- director prompt: action continuity, prop stability, identity anchors, and scene constraints
- end-frame prompt: the intended final keyframe for first/last-frame video workflows
- negative prompt: identity drift, flicker, new strangers, prop disappearance, and still-image failure

Candidate videos store the shot plan in their `.quality.json` report, so bad
shots can be debugged from evidence instead of guessing.

When a prompt-aware ComfyUI video workflow is configured, the platform can also
generate a scene end keyframe and pass it through `{end_image}` or
`{last_frame}`. This is the preferred contract for Wan/FramePack/Kling-style
first/last-frame generation because the model receives both the starting visual
state and the intended ending visual state.

## Why This Matters

Seed Dance-like quality requires the business pipeline to control more than one
prompt string. It needs:

- atomic shot splitting
- character identity references
- director-style movement instructions
- multiple candidates
- sampled-frame review
- retry/refinement
- final composition only after review

The current implementation adds the missing director layer and keeps the backend
ready for stronger local or API engines. The next quality jump should come from
replacing `COMFYUI_VIDEO_WORKFLOW_PATH` with a stronger workflow, such as
Wan/AnimateDiff/FramePack/Kling-compatible ComfyUI nodes, while keeping the same
task logic.

The same contract can also target a production HTTP video gateway. Set
`GENERATION_PROVIDER=http_video_api` and configure `HTTP_VIDEO_ENDPOINT` plus
`HTTP_VIDEO_API_KEY`. The gateway receives a JSON body containing:

- `prompt`
- `negative_prompt`
- `reference_image` as a data URL or original URL
- `end_image` as a data URL or original URL
- `references`: labelled image/video/audio references (`Image1`, `Video1`, `Audio1`)
- `audio`: optional audio reference, `generate_audio`, `multi_shot`, and `shot_plan`
- `duration_seconds`, `aspect_ratio`, `width`, `height`, `fps`, `seed`

For production workflow parity, the `shot_plan` also carries the frozen spatial
contract. A local workflow can consume `{spatial_plan_json}`,
`{spatial_control_references_json}`, and `{spatial_asset_pack_json}` (or
`{spatial_scene_contract_hash}`). Production preflight requires these spatial
inputs; a workflow that only records them as metadata is intentionally blocked.

The gateway may return `video_url` or `video_base64` immediately. For async
providers, it may return `job_id`; then set `HTTP_VIDEO_STATUS_ENDPOINT` with a
`{job_id}` placeholder and return `video_url` or `video_base64` from the status
endpoint when complete.

For a Seedance-compatible reference gateway, use
`GENERATION_PROVIDER=seedance_api`. Configure `SEEDANCE_ENDPOINT`,
`SEEDANCE_API_KEY`, and optionally `SEEDANCE_STATUS_ENDPOINT`. This adapter sends
the explicit `image_urls`, `video_urls`, and `audio_urls` arrays, plus
`generate_audio`, `resolution`, and the continuity-aware structured
`shot_plan` folded into the prompt.
Hosted gateways may use different authentication or queue response shapes, so
their endpoint and status URL remain configurable.

The workbench can override `provider`, `model`, `request_mode`, `multi_shot`, and
`native_audio` for one run through `POST /api/projects/{project_id}/produce`.
Blank or omitted provider/model values continue to use the environment defaults.
The selected model is carried through the Celery task and native Ark payload;
its 4K, MOV, Draft, and reference-limit capabilities are validated before
submission.

For the native Volcano Ark task API, set `SEEDANCE_API_FORMAT=ark_v3`. The
adapter then emits `content[]` with explicit `reference_image`,
`reference_video`, `reference_audio`, `first_frame`, and `last_frame` roles,
plus the native model, ratio, resolution, duration, and audio fields. Use the
2.5 model limits only when the configured model is a confirmed 2.5 endpoint.
Local images use Base64 data URLs; local video references must be exposed with
`SEEDANCE_MEDIA_URL_TEMPLATE` or pre-ingested as `asset://` material, because
the native task API cannot fetch a filesystem path.

Transient submit/status failures (HTTP 408/409/425/429 and 5xx, plus transport
errors) are retried with exponential backoff. Configure the bounds with
`SEEDANCE_MAX_RETRIES` and `SEEDANCE_RETRY_BACKOFF_SECONDS` (or the corresponding
`HTTP_VIDEO_*` settings).

Every new generation request also sends a stable SHA-256 request fingerprint as
`Idempotency-Key` by default. This lets gateways deduplicate a paid POST when the
network fails after acceptance but before the local pending-task sidecar is saved.
Set `SEEDANCE_IDEMPOTENCY_ENABLED=false` (or the corresponding `HTTP_VIDEO_*`
setting) only for gateways that explicitly reject idempotency headers.

Set `SEEDANCE_CALLBACK_URL` when the Ark account has a reachable callback
endpoint. The provider includes the documented callback field while retaining
status polling as a recovery path.

The default Seedance adapter sends only the documented hosted-model fields and
folds the internal negative prompt and continuity contract into `prompt`. Set
`SEEDANCE_REQUEST_MODE=multi_shot` for a gateway that explicitly supports the
Seedance 2.5-style multi-shot contract; this adds `multi_shot` and `shot_plan`.
`SEEDANCE_INCLUDE_EXPERIMENTAL_FIELDS=true` remains available for gateways that
also require the extra model/seed/end-frame fields.

For native Seedance 2.5, first/last-frame generation is sent as `adaptive` and
`1080p`, as required by Ark. Draft promotion is a separate request using the
returned `draft_task_id`; the adapter sends `1080p` and only the output controls
that Ark allows to be changed in the second step.

## Key Settings

```env
SVD_NUM_FRAMES=25
SVD_FPS=8
GENERATION_VIDEO_TARGET_SECONDS=3.6
GENERATION_VIDEO_MAX_SECONDS=6.0
GENERATION_VIDEO_MODEL_FPS=8
GENERATION_VIDEO_MAX_FRAMES=40
GENERATION_VIDEO_OUTPUT_FPS=24
GENERATION_VIDEO_POSTPROCESS=true
GENERATION_VIDEO_END_FRAME_ENABLED=true
GENERATION_VIDEO_CANDIDATES=2
GENERATION_VIDEO_REFINEMENT_PASSES=1
GENERATION_REQUIRE_VIDEO_REVIEW=true
COMFYUI_VIDEO_WORKFLOW_PATH=
GENERATION_PROVIDER=local_comfyui
HTTP_VIDEO_ENDPOINT=
HTTP_VIDEO_API_KEY=
HTTP_VIDEO_STATUS_ENDPOINT=
```

Production workflows should expose these placeholders when the backend supports
them:

```env
{prompt}
{negative_prompt}
{reference_image}
{end_image}
{last_frame}
{seed}
{fps}
{output_prefix}
```

Final production readiness requires `GENERATION_REQUIRE_VIDEO_REVIEW=true` and a
running local llama.cpp VLM reviewer. Keep it false only for draft/debug runs.

By default, final composition uses the separately reviewed dialogue/TTS track.
When the workbench enables `native_audio` for a run and every accepted provider
clip records a valid native audio stream, the composer now preserves that
per-run audio automatically. The global
`GENERATION_PREFER_NATIVE_VIDEO_AUDIO=true` switch remains available as an
explicit override; in both cases the composer verifies every scene has an
audio stream, preserves it during concat, and skips TTS replacement.

## Seed Dance Replacement Gate

Do not mark a run as a Seed Dance replacement candidate until it has all of:

- production preflight passing
- sampled-frame VLM review passing
- human/manual review scores present and all accepted
- measurable comparison against a Seed Dance reference clip passing

Run the baseline comparison after generating a representative clip:

```powershell
python -m scripts.validate_local_generation compare-baseline `
  --candidate storage\projects\2\final_preview.mp4 `
  --baseline path\to\seed_dance_reference.mp4 `
  --output storage\validation
```

Then summarize the full validation folder:

```powershell
python -m scripts.validate_local_generation summarize --output storage\validation
```

The summary status must be `ready_for_seed_dance_candidate`. If it is
`partial_needs_review`, read the `action_items` first; the platform should not
claim replacement quality while any gate is missing.
