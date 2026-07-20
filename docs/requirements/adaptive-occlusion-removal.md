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
- Prefer a configured local detector command for unknown logos/watermarks. If no
  detector is configured, only a conservative bottom-subtitle heuristic is used.
- Use temporal video inpainting backends such as ProPainter, Video Subtitle
  Remover, or another configured local video-inpaint command.
- Reject outputs when the quality score is lower than
  `OCCLUSION_MIN_QUALITY_SCORE`.
- Mark risky jobs as `needs_review`; do not continue into ASR with damaged video.

## Configuration

```env
OCCLUSION_REMOVAL_BACKEND=auto_video_inpaint
OCCLUSION_MASK_DETECTOR_COMMAND=
OCCLUSION_AUTO_MASK_MIN_CONFIDENCE=0.65
OCCLUSION_MIN_QUALITY_SCORE=0.92
OCCLUSION_REMOVAL_TIMEOUT_SECONDS=7200
AUTO_VIDEO_INPAINT_COMMAND=
PROPINTER_COMMAND=
VSR_COMMAND=
```

Detector command templates receive:

- `{input}`: source video path
- `{output}`: JSON path where mask candidates must be written

Detector output format:

```json
{
  "detector": "local-mask-detector-v1",
  "notes": ["optional notes"],
  "candidates": [
    {
      "source": "ocr_text",
      "confidence": 0.94,
      "x": 0.04,
      "y": 0.78,
      "width": 0.92,
      "height": 0.16,
      "start_sec": 0.0,
      "end_sec": null
    }
  ]
}
```

Inpainting command templates receive:

- `{input}`: source video path
- `{output}`: cleaned video path
- `{mask}`: normalized mask-candidate JSON path
- `{plan}`: full cleaning plan JSON path

Example shape:

```env
OCCLUSION_MASK_DETECTOR_COMMAND=python C:/models/mask-detector/detect.py --video {input} --output {output}
PROPINTER_COMMAND=python C:/models/ProPainter/inference_propainter.py --video {input} --mask {mask} --output {output}
```

## Quality Rule

The system should prefer stopping for review over producing a visibly damaged
export. Known high-risk cases include subtitles over faces, subtitles over fast
motion, transparent watermarks over detailed texture, and multiple watermarks
with different motion patterns.
