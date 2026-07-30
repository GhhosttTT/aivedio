# Local Subtitle Translation Workflow

## Purpose

After ASR creates `transcript.json`, the localization pipeline translates each
timed Chinese segment into every target language while preserving the original
time ranges.

```text
transcript.json
 -> local LLM or command backend
 -> en/es/pt/ar/id/th/vi/ja/ko JSON + SRT
```

## Output Contract

For each target language, the service writes:

- `{language}.json`
- `{language}.srt`

The JSON format is:

```json
{
  "language": "en",
  "segments": [
    {
      "start": 0.0,
      "end": 1.25,
      "text": "Hello"
    }
  ]
}
```

Timing must remain aligned with the ASR transcript. Translation changes only
`text`.

## Local LLM Backend

```env
TRANSLATION_BACKEND=local_llm
TRANSLATION_MAX_SEGMENTS_PER_BATCH=30
```

The LLM prompt requires strict JSON output:

```json
{"segments":[{"index":1,"text":"translated text"}]}
```

## Command Backend

Use command mode to call a local translation script or another local model
runtime.

```env
TRANSLATION_BACKEND=command
TRANSLATION_COMMAND=python C:/models/translator/translate.py --input {input} --output {output} --language {language}
```

Template variables:

- `{input}`: source transcript JSON path
- `{output}`: translated JSON output path
- `{language}`: target language code
- `{language_name}`: English display name

## Quality Notes

- Keep segment count exactly the same as the source transcript.
- Preserve timestamps.
- Use natural short-drama dialogue, not literal textbook translation.
- Arabic requires RTL-aware rendering later in the subtitle rendering stage.
