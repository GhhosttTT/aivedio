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
- `duration_seconds`, `aspect_ratio`, `width`, `height`, `fps`, `seed`

The gateway may return `video_url` or `video_base64` immediately. For async
providers, it may return `job_id`; then set `HTTP_VIDEO_STATUS_ENDPOINT` with a
`{job_id}` placeholder and return `video_url` or `video_base64` from the status
endpoint when complete.

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
GENERATION_REQUIRE_VIDEO_REVIEW=false
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

For production review, set `GENERATION_REQUIRE_VIDEO_REVIEW=true` after a local
VLM reviewer is running.

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
