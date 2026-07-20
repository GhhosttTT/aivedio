# Parallel Source-Video Localization Workflow

## Core Rule

Video cleanup and audio transcription are independent preprocessing branches and
must run at the same time.

```text
                 -> visual cleanup -> clean master video -
source video ----                                      ----> translate -> render -> moderate
                 -> audio ASR ------> Chinese timed subtitles
```

## Branches

### Visual Branch

```text
source video
 -> detect subtitle/watermark masks
 -> track masks across time
 -> protect faces, bodies, and strong edges
 -> local video inpainting
 -> quality gate
 -> clean master video
```

This branch exists only to create a visually clean master. It should not block
audio transcription unless the whole job is cancelled.

### Audio Branch

```text
source video
 -> extract audio
 -> ASR with timestamps
 -> Chinese SRT/transcript
 -> local LLM localization prompts
```

This branch should read the original audio track, not the cleaned video. Visual
cleanup may change frames, but it should not be required for ASR.

## Join Point

Translation starts only after:

- the visual branch has produced a clean master video or entered review;
- the audio branch has produced timestamped Chinese subtitles.

Rendering starts only after translated subtitles are available for the selected
target languages.

## Why This Matters

Running the branches sequentially wastes time. A 90-second short drama can spend
most of its processing time in video inpainting, while ASR is much faster and can
finish in parallel. This matches the cloud-style production logic while still
keeping the models local.
