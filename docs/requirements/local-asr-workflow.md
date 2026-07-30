# Local ASR Workflow

## Purpose

The localization pipeline needs a timed Chinese transcript before translation.
ASR runs in parallel with visual cleanup and reads the original source video
audio, not the cleaned video.

## Output Contract

Each ASR run writes:

- `source.wav`: mono 16 kHz extracted audio
- `transcript.json`: machine-readable timed transcript
- `transcript.zh.srt`: Chinese subtitle file for review and translation

`transcript.json` format:

```json
{
  "language": "zh",
  "segments": [
    {
      "start": 0.0,
      "end": 1.25,
      "text": "你好"
    }
  ]
}
```

## Backends

### faster-whisper

```env
ASR_BACKEND=faster_whisper
ASR_MODEL_PATH=./models/faster-whisper-large-v3
ASR_DEVICE=cuda
ASR_COMPUTE_TYPE=float16
ASR_LANGUAGE=zh
```

### Command Backend

Use this when the ASR model is exposed through a local script or another local
runtime.

```env
ASR_BACKEND=command
ASR_COMMAND=python C:/models/asr/transcribe.py --audio {audio} --output {output} --language {language} --model {model}
```

The command must write the same JSON shape shown above.

## Notes

- `ffmpeg` must be available on PATH for audio extraction.
- ASR failures should stop localization before translation, because all target
  languages inherit transcript mistakes.
