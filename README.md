# Camera Agent

A provider-neutral prototype for a camera and imagery-focused AI agent.

The core loop is:

1. Plan from the current image and user prompt.
2. Compile planned actions into registered tool calls.
3. Execute deterministic, vision, generative, and composite tools.
4. Evaluate the result against the original image and request.
5. Replan when the evaluator reports that requirements are still missing.

Agno is used only for structured multimodal planner/evaluator agents. Execution, state, history, tool registration, and provider clients are plain Python modules. Default planner: DeepSeek (`deepseek-v4-flash`) + local Qwen3-VL vision bridge (`:8000`). Default evaluator: local MiniCPM-V-4.6 dual-image on `:8001` (see [docs/minicpm_evaluation.md](docs/minicpm_evaluation.md)).

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

### Edit loop (`app.py`)

The default config expects `DEEPSEEK_API_KEY`, a local **Qwen3-VL** vision bridge at
`http://127.0.0.1:8000`, local **MiniCPM-V-4.6** at `http://127.0.0.1:8001/v1`
(evaluator; no API key), and **ComfyUI** at `http://127.0.0.1:8188`. Start all three with
`bash scripts/restart_required_services.sh`. See `docs/development_workflow.md` §3.5 and
`docs/minicpm_evaluation.md`.

```bash
python app.py \
  --image test_img/stand_female_0.jpg \
  --prompt "Change the background to a sunny beach while preserving the person."
```

### Shooting slow path P1 (`app_shooting.py`)

Qwen3-VL does scene description + fixed aesthetic edit draft (**no user intent** in the
aesthetic call). The main Agent asks clarifying questions and produces `ShootingPlan` +
final `editInstruction`. Needs `:8000` + `DEEPSEEK_API_KEY` (not MiniCPM/Comfy for P1).

```bash
python app_shooting.py \
  --image test_img/02-input_frame.jpg \
  --prompt "在断桥拍游客照，湖面和远山，人物在右侧"
```

### Gateway P2 (H5 + FastAPI)

Same shooting loop over HTTP; gallery upload or one-shot camera (no live preview stream).
See [docs/p2_gateway_access.md](docs/p2_gateway_access.md) and [docs/p2_ui.md](docs/p2_ui.md).

```bash
uvicorn services.gateway.main:app --host 0.0.0.0 --port 8787
# http://127.0.0.1:8787/   mock UI: /?mock=1
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
