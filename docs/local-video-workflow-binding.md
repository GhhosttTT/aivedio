# Local video workflow binding

The local engine accepts two workflow integration modes:

1. Placeholder mode for existing custom API workflows.
2. Sidecar binding mode for standard ComfyUI API exports, including official
   Wan 2.2 workflows.

Sidecar mode is preferred for upstream workflows. It updates concrete node
inputs and keeps the downloaded graph structurally unchanged. Generate a draft:

```powershell
python -m scripts.scaffold_video_workflow_bindings configs/wan22_api.json
```

The command writes `configs/wan22_api.bindings.json`. It exits with code 2 when
prompt or image nodes are ambiguous. Review every unresolved control and set
`node_id` plus `input` manually. Do not accept an automatically discovered
binding without checking the exported API graph.

Minimum production bindings are positive and negative prompts, opening and
closing images, width, height, native frame count, every active sampler seed,
output FPS, and output filename prefix. Wan 2.2 high-noise/low-noise graphs must
bind the same seed to both sampling stages. The binding file is included in the
frozen workflow profile and sample-validation fingerprint, so changing any
binding invalidates earlier approval.

Example:

```json
{
  "version": 2,
  "model_profile": "wan_2_2",
  "bindings": {
    "positive_prompt": {"node_id": "89", "input": "text"},
    "negative_prompt": {"node_id": "72", "input": "text"},
    "reference_image": {"node_id": "97", "input": "image"},
    "end_image": {"node_id": "98", "input": "image"},
    "num_frames": {"node_id": "74", "input": "length"},
    "seed": [
      {"node_id": "81", "input": "noise_seed"},
      {"node_id": "78", "input": "noise_seed"}
    ],
    "fps": {"node_id": "114", "input": "fps"},
    "output_prefix": {"node_id": "114", "input": "filename_prefix"}
  },
  "derived_controls": [
    "quality_mode",
    "repair_action",
    "quality_pipeline",
    "spatial_plan_json"
  ]
}
```

Node IDs above are illustrative. Use IDs from the workflow exported by the
target ComfyUI installation.

Quality, repair, camera, blocking, and performance directives are compiled into
the positive and negative prompts before binding. Their JSON forms remain audit
evidence unless a custom workflow declares and implements native controls for
them. A metadata node containing `quality_pipeline_json` does not prove that the
sampler consumed it.

Placeholder mode remains supported. Only placeholders are substituted; fixed
values remain unchanged. This preserves per-stage resolution, seeds, and detail
settings in multi-stage workflows.

For example, `"length": "{num_frames}"` becomes a JSON integer, even though
the input field has a different name. `"width": 1536` remains 1536, while
`"width": "{width}"` receives the requested width. Embedded placeholders such
as `"shot-{seed}"` produce text. Substitution happens once: literal braces in
an inserted prompt remain literal.

## Timing inputs

`{num_frames}`, `{video_frames}`, and `{frame_count}` all resolve to
`ceil(duration_seconds * fps)`. `{fps}` and `{duration_seconds}` are also
available. A 5.05-second shot at 16 fps requests 81 frames. Invalid, nonfinite,
or nonpositive timing is rejected before uploading reference assets.

Some video models impose additional frame-count constraints. Adapt the frame
count with that model's workflow nodes before sampling; these aliases do not
claim to satisfy a particular model's temporal alignment. A fixed frame count
in a template stays fixed. Review the resulting duration before production.

## Reference inputs

Opening frame aliases: `{reference_image}`, `{image}`, `{start_image}`,
`{first_frame}`. Closing frame aliases: `{end_image}`, `{last_frame}`.
Previous-shot frame aliases: `{continuity_reference_image}`,
`{continuity_image}`, `{previous_last_frame}`.

LTX-style temporal keyframes use `keyframe_images` and `keyframe_indices` as
parallel arrays; `keyframe_strengths` is available when the target node accepts
per-frame weights, and `keyframe_roles` carries audit labels. A custom node may
consume `keyframe_images_json` instead.
Each JSON item contains the uploaded `path`, zero-based `frame_index`,
`strength`, and semantic `role`. Bind these controls only to a temporal
conditioning node. An ordinary reference-image list does not establish frame
timing and must not be used as a substitute.

When `GENERATION_VIDEO_MID_KEYFRAME_ENABLED=true`, the director creates one
internal anchor for a simple shot and up to
`GENERATION_VIDEO_MAX_MID_KEYFRAMES` anchors for high-action, prop-interaction,
long, or performance-heavy shots. Anchors describe distinct action phases and
are assigned strictly increasing frame indices. They are generated as a
continuity chain: opening frame -> early anchor -> late anchor -> closing
frame. Each image uses the previous accepted image as its structural reference
and retains the character-sheet references for identity. Character start/end
states, prop ownership, hand assignment, injuries, wardrobe, blocking, and
declared transition rules are compiled into the matching temporal phase.

This chaining reduces incompatible independently generated poses, but it can
also accumulate image drift. Every anchor therefore passes the normal image
candidate review, is hashed into request evidence, is compared against the
generated video at its requested timestamp, and is compared again after FPS
normalization. Configure a real keyframe-aware workflow before enabling the
feature; preflight blocks a graph that only exposes ordinary reference images.

`{reference_images_json}`, `{reference_videos_json}`, and
`{reference_audios_json}` contain JSON strings listing uploaded inputs. Count
placeholders are `{reference_image_count}`, `{reference_video_count}`, and
`{reference_audio_count}`. The consuming nodes must parse those strings.

Standard single-file loader nodes should use `{driving_video}` and
`{performance_audio}` instead. These values contain the first uploaded video or
audio filename and can be bound directly to `LoadVideo`/`LoadAudio` inputs.
Wan 2.2 Animate and motion-driven HunyuanCustom routes require a real
`driving_video` binding. HunyuanVideo-Avatar performance routes require a real
`performance_audio` binding. A JSON string stored in a metadata node does not
satisfy either contract. The binding scaffold detects one unambiguous video
loader and one unambiguous audio loader automatically; multiple loader nodes
must be assigned manually.

Preflight resolves these inputs using sample asset names to validate the node
contract. It does not generate media or establish model quality. First/last
frame control, identity retention, action following, and dialogue timing still
require actual samples on the target GPU.

## Motion direction source

The director uses the scene's original visual description as the action source.
The compiled image prompt remains available for keyframe generation and framing
analysis. This prevents a static keyframe instruction from replacing the action
in the video prompt. If the original description is empty, the director falls
back to the image prompt. Original descriptions may be Chinese; the selected
video model or custom workflow must support their language.

The selected camera movement is used consistently in both the prose and the
structured camera contract. Dialogue text is preserved in full. Long dialogue
still needs timing validation and, where necessary, scene splitting; increasing
prompt length does not increase model context or lip-sync capability.

## Editable shot specification

Each scene in `Project.script.scenes` can carry `shot_spec`. The scene API
returns it and accepts it in `PUT /api/projects/{id}/scenes/{number}` alongside
the existing visual description and visible characters. Omit it to preserve the
current specification; set it to null to clear it. Editing invalidates derived
media through the existing scene-edit path. No database migration is required.

Supported fields are purpose, emotion, duration_seconds, camera_movement,
camera_intensity, action_intensity, performance_intensity,
continuity_constraints, character_states, and continuity_assets. Intensities use low/medium/high;
performance intensity is an integer from 1 to 5. Each character state has a
character_name and optional emotion, action, start_state, and end_state. State
names must be unique and must refer to visible project characters when edited
through the API or parsed from generated scripts. A generated shot that contains
character states must declare its visible characters, and every state name must
belong to that list. Remove or update obsolete states when changing visible
roles.

`continuity_assets` records deterministic production facts that have to cross a
shot boundary. Each item has a stable `asset_id`, a `kind` (`prop`, `wardrobe`,
`injury`, `environment`, `blocking`, or `other`), `start_state`, `end_state`,
`inherits_previous`, and an optional `transition_note`. States are small maps,
for example `{"holder": "Alice", "hand": "right"}` for `prop:knife`.
The next adjacent shot may declare the same asset and its opening state. When a
shared attribute changes while `inherits_previous` is true, a transition note
is required. Use a note for intended events such as a handoff, an outfit change,
or rain soaking a coat. Use a new asset ID for a genuinely different object.

The editor accepts one `key=value` item per line for each opening and ending
state. It rejects blank or duplicate asset IDs before saving. Structured assets
are included in the director prompt and opening-frame contract, so they travel
with the same plan as camera and character direction.

The director consumes these explicit values, carries the specification in its
serialized plan, appends continuity locks and performance direction to the video
prompt, and carries end states into the end-frame prompt. A specified duration
must fit the configured workflow capacity; measured speech can lengthen the
shot within that capacity. The reviewer receives the same specification.
The script generator accepts a single-line JSON `镜头规格` field; older text
templates contribute their story beat and emotion when this field is absent.

This is the shared direction contract's first implementation. The script
workbench provides a dedicated editor and read-only summary for these fields.
It validates the duration and performance ranges before saving, removes blank
continuity lines, and excludes states for roles that are no longer visible.
Reference asset binding and generation parameters still use the existing
production contracts. State transitions are instructions, not a physical
simulation or proof that a model follows them. Deterministic cross-shot
state-transition validation remains further work.

Production readiness performs a conservative adjacent-shot state audit. It
reports an explicit left/right hand flip between one shot's end state and the
next shot's start state when neither state declares a handoff. It also compares
matching structured asset attributes across adjacent shots and reports an
undeclared change. These are review warnings, not proof of a visible mismatch;
free-form movement and non-adjacent scenes are intentionally not inferred.

## Frozen continuity asset pack

When a project uses `continuity_assets`, freeze the approved project snapshot
with `POST /api/projects/{project_id}/freeze-continuity-assets`. The manifest
is stored under the project continuity directory and includes every scene's
asset state, a per-scene hash, and a project signature. Image and video tasks
use the approved opening or ending asset states as generation directives.

Changing a scene's visual description or its asset state invalidates the pack.
Generation then stops before submitting a new provider job until the pack is
frozen again. Projects that do not declare any structured continuity assets
remain compatible and report this gate as `not_configured`.

The workbench's **连续性资产锁** section freezes this pack alongside the
spatial plan and visual style. A stale pack appears as a production repair
action. This contract establishes state provenance; model output still needs
frame review because a frozen prompt does not prove visual compliance.

## Reference-image identity scoring

`POST /api/projects/{project_id}/characters/{character_id}/identity-score-image`
uses the configured local llama.cpp VLM to inspect one already registered
character reference image. The VLM returns canonical observations for facial
geometry, eyes, eyebrows, nose, mouth, jawline, hair, skin tone, distinctive
mark, and wardrobe; those observations are then scored against the frozen
identity specification. The endpoint accepts only a reference path already
registered for that character, so it cannot be used to read arbitrary local
files. A VLM score remains review evidence and needs calibration against real
approved cast references before it becomes a commercial-quality acceptance
threshold.

Keyframe compilation consumes a separate opening-frame contract containing
emotion, each character's start state, and continuity locks. End states and
motion instructions are excluded from this input so the compiler does not draw
the completed action in the starting image. The image reviewer receives this
opening-frame contract as well. The complete specification participates in the
compiled-prompt cache key and story-review fingerprint; changing the plan
requires recompilation and renewed story approval even if the visual sentence
has not changed. This binds the input contract, while real image inspection is
still required to establish that visible constraints were followed.
