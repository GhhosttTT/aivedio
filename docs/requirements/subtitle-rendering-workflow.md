# Multilingual Subtitle Rendering Workflow

## Purpose

After translation, each target-language SRT is burned into the clean master
video to produce release-ready MP4 files.

```text
clean master video + translated SRT files
 -> FFmpeg subtitle rendering
 -> en.mp4 / es.mp4 / pt.mp4 / ar.mp4 / ...
```

## Inputs

- `source_video.clean_video_path`: clean master video from visual cleanup
- `localization_job.translated_subtitle_dir`: directory containing `{lang}.srt`
- target language list from `localization_job.target_languages`

## Outputs

The renderer writes:

- `{lang}.mp4` for each target language
- `rendered_videos.json` manifest

Manifest shape:

```json
{
  "clean_video_path": "storage/project_1/localization/job_1/cleaning/source_clean.mp4",
  "videos": {
    "en": {
      "language": "en",
      "subtitle_path": "storage/project_1/localization/job_1/translations/en.srt",
      "video_path": "storage/project_1/localization/job_1/rendered/en.mp4"
    }
  }
}
```

## Configuration

```env
SUBTITLE_RENDER_FONT=Arial
SUBTITLE_RENDER_FONT_SIZE=26
SUBTITLE_RENDER_MARGIN_V=48
SUBTITLE_RENDER_TIMEOUT_SECONDS=7200
```

## Notes

- Rendering preserves the original audio track.
- Arabic is flagged as RTL-sensitive; final typography quality still depends on
  the installed font and FFmpeg/libass shaping support.
- If a language SRT is missing, rendering fails clearly instead of silently
  skipping the language.
