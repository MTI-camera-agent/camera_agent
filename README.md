# Camera Agent

A provider-neutral prototype for a camera and imagery-focused AI agent.

The core loop is:

1. Plan from the current image and user prompt.
2. Compile planned actions into registered tool calls.
3. Execute deterministic, vision, generative, and composite tools.
4. Evaluate the result against the original image and request.
5. Replan when the evaluator reports that requirements are still missing.

Agno is used only for structured multimodal planner/evaluator agents. Execution, state, history, tool registration, and provider clients are plain Python modules. The default Gemini Developer API config uses Agno JSON mode and then validates the response locally with Pydantic.

## Layout

- `agents/`: thin perception, planner, and reflector wrappers.
- `models/`: provider adapters and factories.
- `schemas/`: Pydantic contracts for plans, actions, tools, state, and reports.
- `tools/`: registered deterministic, vision, generative, and skill-like composite tools.
- `workflow/`: compiler, executor, state snapshots, and image loop.
- `prompts/`: editable planner and evaluator instructions.
- `tests/`: unit and opt-in live integration tests.

For a full module-by-module guide, extension recipes, and architecture notes, read
[docs/project_guide.md](docs/project_guide.md).

## Run

The default config expects `GEMINI_API_KEY` and an OpenAI-compatible image service at `http://127.0.0.1:8010`.

```bash
python app.py \
  --image test_img/stand_female_0.jpg \
  --prompt "Change the background to a sunny beach while preserving the person."
```

The app prints a structured trajectory by default: planning, compiled actions,
tool calls, artifacts, and evaluation. Use `--trace-format json` for JSON-lines
events or `--trace-format none` for quiet output.

To deliberately exercise replanning, disable the background refinement substep
for the first iteration only:

```bash
python app.py \
  --trace-format plain \
  --max-iterations 3 \
  --debug-disable-refine-first-iteration \
  --image test_img/stand_female_1.jpg \
  --prompt "Change the background to a sunny beach."
```

Plans are written to `outputs/plans`, state snapshots to `outputs/logs`, masks to `outputs/masks`, and final images to `outputs/images`.

## Tests

Run default tests:

```bash
pytest
```

Run live integration checks only when the Gemini key and image service are available:

```bash
RUN_LIVE_AGENT_TESTS=1 pytest tests/test_live_integration.py -q -s
```

## Provider Boundaries

Core workflow code does not instantiate providers directly. Provider-specific construction lives in `models/factory.py` and adapter modules. To add a provider, implement the relevant protocol in `models/protocols.py`, register it in the factory, and reference it from `config.yaml`.
