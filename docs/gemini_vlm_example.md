# Gemini 2.5 Flash VLM Example

The example script uses Google AI Studio through the `google-genai` SDK.
Do not commit API keys. Set the key in your shell:

```bash
export GEMINI_API_KEY='your-google-ai-studio-api-key'
```

Run both examples:

```bash
python scripts/gemini_vlm_example.py
```

Responses stream by default. Disable streaming with:

```bash
python scripts/gemini_vlm_example.py --no-stream
```

Test Google Search tool use:

```bash
python scripts/gemini_vlm_example.py search
```

The script does not print tool notices just because a tool is available. It
prints `[tool] used ...` only when the Gemini response metadata indicates an
actual tool call or Google Search grounding event.

For Google Search grounding, Gemini API exposes usage through
`grounding_metadata`, including search queries or source chunks. For custom
function tools, usage is detected through returned `function_call` or
server-side `tool_call` parts.

Describe a local image:

```bash
python scripts/gemini_vlm_example.py image --image test_img/stand_female_0.jpg
```

The default model is `gemini-2.5-flash`. Override it with `--model` if needed.
