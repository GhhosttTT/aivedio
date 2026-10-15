# Local Short-Drama Quality Work, 2026-10-15

This pass targets generation behavior and repair correctness. GPU model rendering and commercial visual quality have not been established by these code changes.

## Generation Changes

- Image search uses the same full acceptance criteria as final selection. A high average cannot end search when identity, aesthetic, reference, or turnaround checks fail.
- Passing candidates rank ahead of rejected candidates. Seed-reference and ultra profiles search at least two batches by default, within the configured refinement budget.
- Repair feedback follows the strongest candidate. Generator prompts describe visible corrections; raw criticism stays in reports instead of the positive prompt.
- A failed candidate does not discard the remaining image/video candidates. A ComfyUI observation timeout stops the task without resubmitting its potentially live GPU job.
- Accepted keyframes are retained as `.accepted` images. Postprocessing failure restores accepted pixels, and postprocessing reports must preserve resolution and framing.
- End-frame generation now uses candidate selection and final image review, including separate cast references for multi-character shots.
- Video seeds are stable across Python processes and output directories. Secondary image-stage seeds are derived separately from the base seed.
- Character reference APIs reuse the approved identity bible. A turnaround album reuses an existing casting reference or first selects one master portrait; every angle then uses that same image for generation and review.
- Expression sheets use head-and-shoulders framing. Body-angle sheets use full-body framing. Rear-view review records facial geometry as unobservable rather than inventing a face score.

## Workflow Execution

Image graph traversal follows node edges rather than JSON order. It locates the base sampler, updates each active conditioning branch, preserves detail-pass denoise/steps/CFG, and keeps existing identity/model patches connected.
All active sampling and face-detail stages must retain the identity adapters. The selected candidate's actual workflow and job metadata accompany its promoted image.

Three opt-in templates are included:

| Template | Purpose |
| --- | --- |
| `configs/comfyui_workflow_sdxl_multistage.json` | Composition, latent upscale, low-denoise detail, final decode |
| `configs/comfyui_workflow_sdxl_multistage_reference.json` | The same stages with one FaceID reference |
| `configs/comfyui_workflow_sdxl_regional_two_character.json` | Two independent FaceID references with disjoint left/right attention masks |

These templates use the existing Juggernaut checkpoint name. The reference templates need the matching local SDXL FaceID assets and ComfyUI IPAdapter nodes. They do not provide pose/depth control or a complete approved production profile on their own.

The two-character template binds the first visible character to frame left and the second to frame right, matching the existing composition contract. It does not infer arbitrary blocking or solve crowd shots. Shots with a different cast count need matching reference slots or should be split.

Example configuration after local asset verification:

```dotenv
COMFYUI_WORKFLOW_PATH=./configs/comfyui_workflow_sdxl_multistage.json
COMFYUI_REFERENCE_WORKFLOW_PATH=./configs/comfyui_workflow_sdxl_multistage_reference.json
COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH=./configs/comfyui_workflow_sdxl_regional_two_character.json
GENERATION_MIN_QUALITY_PASSES=2
GENERATION_VIDEO_MAX_FREEZE_SECONDS=0.2
```

If a video workflow saves multiple independent outputs, set `COMFYUI_VIDEO_OUTPUT_NODE` to the final save node ID. Preview PNGs are never accepted as generated video. After changing workflow files or quality settings, revalidate and freeze the production workflow profile.

The 1.5x latent detail pass increases GPU memory and rendering time. Parameter optimization preserves the requested aspect ratio when reducing resolution, but local VRAM limits still need real measurement.

ComfyUI retries are bounded by side effects: connection failures before submission can retry, and artifact downloads retry against the same completed job. Ambiguous submission outcomes and observation timeouts do not resubmit. A `.job.json` sidecar records the prompt ID, workflow hash, chosen output node and job state. Reconcile `observation_required` jobs with the local ComfyUI queue/history before a manual rerun; automatic job resumption is not implemented. Downloads validate a temporary file before replacing an existing artifact.

## Repair And Timing

- One automatic repair iteration shares one task record. Audio and subtitles finish before dependent video, and the whole batch receives one final generation review.
- Validation completes before invalidating any scene assets. Queue-dispatch failure restores previous paths and project state.
- Project reservation blocks overlapping production/repair submissions. Progress increments happen atomically and terminal repair tasks release the project for further work.
- Video planning uses measured dialogue duration when available. Overlong dialogue needs a shot split or a longer configured video workflow.
- Normalization permits only a small rounding gap to be filled with a frozen final frame. Large duration shortages require regeneration.
- Composition checks duration per scene, pads each dialogue track to that scene, and inserts silence for no-dialogue shots. Independent audio concatenation can no longer shift later dialogue across scene boundaries.
- Review fingerprints include audio and subtitles as well as image/video bytes. Audio-only repairs refresh sampled-frame review when the complete set of scene videos is available.
- Subtitles must cover the complete normalized dialogue text; a short prefix is insufficient.

## Local Validation

The default sample set now includes a two-character confrontation. Set its `character_references` to two real frozen images, in the same left-to-right order as `visible_characters`:

```json
"character_references": [
  {"name": "Alice", "path": "C:/assets/alice_front.png"},
  {"name": "Victor", "path": "C:/assets/victor_front.png"}
]
```

These are example paths, not bundled assets. A sample category label alone cannot satisfy regional-identity coverage: the actual graph metadata must show a separately masked identity binding for each visible role. Old six-case validation packages need a fresh two-character sample.

After GPU prerequisites are ready, the opt-in production-search check uses the same candidate search, refinement, postprocessing and local review path as production:

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_local_generation render-images --production-search --cases examples/local_generation_cases.json --output storage/validation
```

The command performs real rendering and has not been run during this code-only pass. It still requires subsequent human review and full-episode validation. Existing generation reviews need to be rerun after the review-fingerprint changes. The reference APIs return HTTP 409 when the character identity bible has not been created.

Postprocess commands launch an executable directly with `shell=False`. Shell operators such as `&&` and `|` require an explicitly configured shell program; ordinary executable/argument templates keep working.

## Verification

Final code verification for this pass:

- Full Python suite: **1175 passed, 7 skipped**, 4866 warnings, in 160.53 seconds. No dependency upgrades were performed to suppress warnings.
- Frontend: TypeScript and Vite production build passed (1444 modules). Browserslist reports outdated browser data.
- Python: `compileall -q src scripts tests` passed.
- Git whitespace check passed with Windows CRLF handling. No unrelated line-ending rewrite was applied.
- A credential-pattern scan of the 55 modified/new files found no credential-shaped strings. This was not a complete repository-history secret audit.

The final tree contains local, uncommitted changes. No commit or GitHub push was made in this pass. The timed follow-up was deleted after the user requested stopping when testing finished.

No real GPU-generated sample or complete episode was produced in this pass. FFmpeg and ffprobe are not available in the current shell. Live ComfyUI nodes/model compatibility, local llama.cpp review calibration, actual media timing, Redis/Celery recovery and cancellation, VRAM use, and render duration still need target-machine integration checks. The new graphs remain opt-in and have not replaced the existing production defaults.

Required next evidence includes local workflow execution, measured VRAM/time per accepted shot, two-character reference separation, face preservation through detail passes, speech timing, and a human-reviewed complete episode. Test results alone cannot establish parity with a commercial video model.
