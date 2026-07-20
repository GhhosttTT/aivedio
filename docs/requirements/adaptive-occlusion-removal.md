# Adaptive Subtitle and Watermark Removal

## Goal

The source-video localization system must handle unknown burned-in Chinese
subtitles and unknown watermarks without damaging the original shot quality.
This is a quality-first stage, not a simple blur, crop, or fixed-position
overlay.

## Required Pipeline

```text
source video
 -> candidate mask detection
 -> temporal mask tracking
 -> face/body/edge protection
 -> video inpainting
 -> quality scoring
 -> pass to ASR or require review
```

## Strategy

- Detect multiple mask candidates instead of assuming one subtitle strip.
- Support subtitle text regions, static logos, moving platform watermarks, and
  manually reviewed masks.
- Use temporal video inpainting backends such as ProPainter, Video Subtitle
  Remover, or another configured local video-inpaint command.
- Reject outputs when the quality score is lower than
  `OCCLUSION_MIN_QUALITY_SCORE`.
- Mark risky jobs as `needs_review`; do not continue into ASR with damaged video.

## Configuration

```env
OCCLUSION_REMOVAL_BACKEND=auto_video_inpaint
OCCLUSION_MIN_QUALITY_SCORE=0.92
OCCLUSION_REMOVAL_TIMEOUT_SECONDS=7200
AUTO_VIDEO_INPAINT_COMMAND=
PROPINTER_COMMAND=
VSR_COMMAND=
```

Command templates receive:

- `{input}`: source video path
- `{output}`: cleaned video path

Example shape:

```env
PROPINTER_COMMAND=python C:/models/ProPainter/inference_propainter.py --video {input} --output {output}
```

## Quality Rule

The system should prefer stopping for review over producing a visibly damaged
export. Known high-risk cases include subtitles over faces, subtitles over fast
motion, transparent watermarks over detailed texture, and multiple watermarks
with different motion patterns.
