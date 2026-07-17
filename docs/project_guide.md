# Camera Agent Project Guide

This document explains how to navigate, extend, and reason about the camera agent codebase.

## Architecture Assessment

The current layout is a good starting point for a scalable prototype. The important boundaries are already in place:

- `schemas/` owns data contracts.
- `agents/` owns model-facing planning and evaluation wrappers.
- `models/` owns provider adapters and factories.
- `tools/` owns executable image operations.
- `workflow/` owns orchestration, compilation, execution, and state snapshots.
- `prompts/` owns model instructions.
- `tests/` owns local and live trajectory checks.

This is better than placing all logic inside Agno agents. Agno is useful for structured multimodal reasoning, but deterministic image operations, tool dispatch, state persistence, and provider selection are clearer and easier to test as normal Python modules.

The main non-optimal parts are expected prototype limitations rather than structural defects:

- `tools/vision/segment.py` is currently a bootstrap mask tool, not model-grade segmentation.
- `memory/` is thin and mostly reserved for future persistence and retrieval.
- The planner currently emits generic `ActionSpec.args`; this is extensible, but each tool still validates required parameters at compile time.
- The loop is sequential. Future work may add action DAG execution, retries per tool, or evaluator-specific replanning strategies.

The project should scale by adding implementations behind existing interfaces, not by adding parallel versions of the same concept.

## Runtime Flow

The main execution path is:

```text
app.py
  -> load config
  -> build model clients through models/factory.py
  -> create default tool registry
  -> create PlannerAgent and ReflectorAgent
  -> ImageLoop.run()
       -> StateManager.initial_state()
       -> PlannerAgent.plan()
       -> PlanCompiler.compile()
       -> ToolExecutor.execute()
       -> ReflectorAgent.evaluate()
       -> stop if satisfied, otherwise replan
```

The loop is implemented in `workflow/image_loop.py`.

The artifact flow is:

```text
input image
  -> ExecutionState.original_image
  -> planner sees current image + user prompt + state summary
  -> plan steps compile into registered tools
  -> tools produce artifacts under outputs/images or outputs/masks
  -> ExecutionState.current_image updates when an image artifact is produced
  -> reflector compares original image and current image
```

Plans are written to `outputs/plans`. State snapshots are written to `outputs/logs`.

Tool args can reference built-in image aliases:

- `original_image`: the user's initial input image.
- `current_image`: the latest image artifact in the loop.
- `latest_image` and `image`: aliases for `current_image`.
- `input_image` and `source_image`: aliases for `original_image`.

## Module Map

### `app.py`

CLI entry point. It wires together config, provider clients, prompts, tools, compiler, executor, state manager, and the image loop.

It should stay thin. Do not put planning logic, provider-specific code, or tool implementation details here.

### `config.yaml`

Runtime configuration. The default config uses:

- `structured_vision.provider: agno.google`
- `structured_vision.model_id: gemini-2.5-flash`
- `structured_vision.use_json_mode: true`
- `image_generator.provider: openai_compatible`
- `image_generator.base_url: http://127.0.0.1:8010`
- `tracing.format: plain`

Provider names are registry keys, not hardcoded workflow assumptions.

### `schemas/`

Pydantic contracts shared across the system.

- `schemas/action.py`: `ActionSpec`, `ActionExecution`, and action status.
- `schemas/plan.py`: `Plan` and `GoalSpec`.
- `schemas/perception.py`: `PerceptionReport`.
- `schemas/state.py`: `Artifact`, `ExecutionState`, and `EvaluationReport`.
- `schemas/tool.py`: tool metadata such as `ToolSpec`, `ToolParameter`, and `ToolLayer`.

These schemas are the most important compatibility layer. Planner output, compiler validation, executor behavior, state persistence, and tests all depend on them.

### `agents/`

Thin wrappers around model-backed reasoning roles.

- `agents/perception.py`: image and prompt to `PerceptionReport`.
- `agents/planner.py`: image, prompt, tool catalog, state summary, and evaluator feedback to `Plan`.
- `agents/reflector.py`: original image, current image, prompt, and state summary to `EvaluationReport`.
- `agents/prompt_loader.py`: loads prompt files from `prompts/`.

These classes should not know which provider is used. They depend only on `StructuredVisionClient`.

### `models/`

Provider boundary.

- `models/protocols.py`: provider-neutral protocols.
- `models/factory.py`: maps config provider keys to concrete adapters.
- `models/agno_structured_vision.py`: Agno-backed structured multimodal client.
- `models/image_generation.py`: OpenAI-compatible image generation/editing client for the local FLUX service.

All provider SDK imports should remain here or in future adapter modules.

### `tools/`

Executable image operations. Tools expose a `ToolSpec` and a `run()` method.

Current layers:

- `tools/traditional/`: deterministic PIL operations such as resize, crop, rotate, blur, and sharpen.
- `tools/vision/`: bootstrap vision utilities such as image metadata and rough subject masks.
- `tools/edit/`: generative image operations backed by the configured image-generation client, including focused operations such as `change_pose` and fallback `edit_image`.
- `tools/composite/`: higher-level skill-like tools that sequence lower-layer tools, such as background replacement.
- `tools/registry.py`: registers tools and provides planner-readable tool catalog text.
- `tools/base/base.py`: shared `ToolContext`, `ToolResult`, and tool protocol.

The planner can only call tools registered in `ToolRegistry`.

### `workflow/`

Provider-neutral orchestration.

- `workflow/compiler.py`: validates planned actions against registered tool specs.
- `workflow/executor.py`: runs compiled tools and records artifacts/history.
- `workflow/history.py`: summarizes state for planner and evaluator context.
- `workflow/state_manager.py`: creates and persists state/plan snapshots.
- `workflow/image_loop.py`: planning, execution, evaluation, and replanning loop.
- `workflow/reporter.py`: structured trajectory output for plans, tool calls, artifacts, and evaluations.

This package should remain plain Python. It should not import provider SDKs.

### `prompts/`

Editable prompt files.

- `perception.md`
- `planner.md`
- `reflection.md`
- `compiler.md`

The planner prompt includes the generated tool catalog. If a tool is not registered, the planner should not be able to use it.

### `memory/`

Reserved persistence helpers.

- `memory/history.py`: line-oriented JSON history store.
- `memory/cache.py`: simple file cache path helper.
- `memory/image_state.py`: compatibility export for `ExecutionState`.

This should evolve only when the loop needs persistent cross-run memory, retrieval, or cache invalidation.

### `utils/`

Small shared helpers.

- `utils/config.py`: YAML loading.
- `utils/file.py`: path and directory helpers.
- `utils/image.py`: image open/save helpers.
- `utils/mask.py`: simple mask creation helpers.
- `utils/logger.py`: logging setup.

Keep utilities small and generic. If a helper becomes domain-specific, move it into the owning package.

### `tests/`

Two classes of tests:

- Default tests run without external services.
- Live integration tests run only with `RUN_LIVE_AGENT_TESTS=1`.

Live integration tests currently verify:

- Gemini planner/evaluator access.
- FLUX local service health.
- A Gemini -> compiler/executor -> FLUX edit -> Gemini reflection trajectory.

## Where Agno Is Used

Agno is used only in `models/agno_structured_vision.py`.

The adapter creates:

- `agno.models.google.Gemini`
- `agno.agent.Agent`
- `agno.media.Image`

The planner and evaluator use Agno through the provider-neutral `StructuredVisionClient` protocol. They do not import Agno directly.

The current config sets `use_json_mode: true`. This follows Agno's documented fallback path for cases where provider-native structured output is not appropriate. Gemini Developer API rejected the native schema generated for the flexible action schema, so the project uses JSON mode and then validates the result locally with Pydantic.

Before changing Agno usage, search the Agno MCP docs first and prefer official examples.

Relevant Agno concepts:

- `Agent(..., output_schema=YourPydanticModel)`
- `Agent(..., use_json_mode=True)` for JSON-mode fallback
- `agent.run(..., images=[Image(filepath=...)])` for image input

## Should Agno Be Used Elsewhere?

Yes, but selectively. The current integration is intentionally conservative: Agno owns model-backed reasoning, while the image workflow remains plain Python. That is the right default for this project because image tools, artifact tracking, filesystem outputs, and provider-specific image services need strict deterministic behavior and simple local tests.

Agno can still improve contributor experience in a few targeted places.

### Good Future Agno Integration Points

#### Planner, Reflector, and Perception Agents

This is the current integration point and should remain the primary one.

Use Agno when a component needs:

- multimodal reasoning over image input,
- typed Pydantic output,
- provider abstraction for model calls,
- prompt-managed decision making.

Current files:

- `agents/planner.py`
- `agents/reflector.py`
- `agents/perception.py`
- `models/agno_structured_vision.py`

This is the cleanest Agno use because the surrounding workflow only sees typed objects such as `Plan` and `EvaluationReport`.

#### Optional Agno Workflow Wrapper

Agno Workflows could wrap the current `ImageLoop` as a higher-level runnable workflow, especially if another Agno agent needs to call the whole camera pipeline as a tool.

This would be useful for:

- exposing the complete image-edit loop to a parent assistant,
- recording workflow sessions in an Agno database,
- composing the camera agent with other research, retrieval, or user-assistance agents.

Do not replace `workflow/image_loop.py` with Agno Workflow yet. Keep the plain Python loop as the source of truth, then optionally adapt it.

Recommended future shape:

```text
workflow/image_loop.py          # source of truth
integrations/agno_workflow.py   # optional Agno Workflow wrapper
```

#### Optional Agno Tool Wrapper Around the Whole Camera Agent

Agno's tool system can expose Python capabilities to an Agno `Agent`. That is useful if a higher-level conversational agent should call the camera pipeline as one tool, for example:

```text
run_camera_edit(image_path, user_prompt) -> final_image_path
```

This is different from registering every low-level image operation as an Agno tool. The recommended boundary is coarse-grained: expose the complete camera workflow as a tool, not every internal PIL or FLUX operation.

#### Shared Memory Later

Agno memory can be useful once the product has persistent users and repeated sessions. For example:

- remember user editing preferences,
- remember preferred output style,
- remember camera or brand constraints,
- share user preferences between planner and reflector agents.

Do not use Agno memory for per-run artifacts such as masks, intermediate images, and plan files. Those belong in `ExecutionState` and filesystem outputs.

### Places Not to Use Agno Yet

#### Low-Level Tool Execution

Keep `workflow/executor.py` plain Python.

Reasons:

- deterministic tools should be debuggable without model calls,
- image artifacts need explicit paths and aliases,
- failures should be normal Python exceptions with clear messages,
- unit tests should run without network, API keys, GPU, or Agno runtime behavior.

#### Tool Registry

Keep `tools/registry.py` plain Python.

The registry is a contract between planner output and executor behavior. Making it an Agno tool registry would blur internal tool execution with model-facing tools and make deterministic validation harder.

#### State Manager

Keep `workflow/state_manager.py` plain Python for now.

The current state files are transparent JSON snapshots. That is more useful during early agent development than hiding state in an SDK-specific persistence layer.

#### Primitive Image Operations

Do not wrap `resize`, `crop`, `rotate`, `blur`, and similar operations as Agno tools unless there is a specific reason for a model to call them directly outside the camera workflow. Internal planner actions plus `PlanCompiler` already provide a cleaner validation boundary.

### Recommended Agno Strategy

Use Agno at reasoning boundaries, not everywhere.

Good:

```text
Image + prompt -> Agno planner -> typed Plan
Original/current images -> Agno reflector -> typed EvaluationReport
Parent assistant -> Agno tool -> run complete camera workflow
```

Avoid:

```text
Every image primitive as an Agno tool
Executor implemented as an Agno agent
State snapshots stored only in Agno memory
Provider SDK imports scattered through workflow or tools
```

This gives contributors a clear rule: if code is making a model-backed decision, Agno may be appropriate. If code is executing deterministic image operations, validating artifacts, or persisting local state, plain Python is usually better.

## Extension Guide

### Add a Traditional Tool

1. Create a module under `tools/traditional/`.
2. Implement a class with:
   - `spec` property returning `ToolSpec`
   - `run(action: ActionSpec, context: ToolContext) -> ToolResult`
3. Register it in `tools/registry.py`.
4. Add tests in `tests/test_executor_tools.py` or a new focused test file.

Minimal shape:

```python
from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult


class ContrastTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="contrast",
            layer=ToolLayer.TRADITIONAL,
            description="Adjust image contrast.",
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="factor", type="number", required=True),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        ...
```

Then add `ContrastTool()` to `create_default_tool_registry()`.

### Add a Generative Tool

Use `context.services` to access configured service clients. For image generation/editing, the existing key is `image_generator`.

Do not instantiate FLUX, OpenAI, Gemini, or other providers directly inside tool modules. Put provider-specific clients in `models/` and inject them through `ToolExecutor(services=...)`.

### Replace the Segmenter

Keep the public action name stable if possible:

```text
segment_subject
```

Replace the implementation behind the registry with a real detector/SAM-backed class. The rest of the workflow should not need to change if the tool still returns a mask artifact.

If the new tool needs a provider client, inject it through `context.services`, for example:

```python
segmenter = context.services["segmenter"]
```

### Add a Model Provider

1. Implement `StructuredVisionClient` or `ImageGenerationClient` from `models/protocols.py`.
2. Register the adapter in `models/factory.py`.
3. Add provider config in `config.yaml`.
4. Add a factory test.
5. Add an opt-in live test if the provider requires network or a local service.

The workflow should not change.

### Change the Evaluator

There are three levels of evaluator change:

- Prompt-only: edit `prompts/reflection.md`.
- Agent wrapper: modify or replace `agents/reflector.py`.
- Provider behavior: add or change a `StructuredVisionClient` adapter in `models/`.

Keep the output contract as `EvaluationReport` unless there is a strong reason to change it. If you change it, update `workflow/image_loop.py`, tests, and docs together.

### Change the Planner

Planner behavior is mostly controlled by:

- `prompts/planner.md`
- `tools/registry.py`
- `schemas/plan.py`
- `schemas/action.py`

If the planner starts emitting richer action structures, update the schema and compiler first, then update tools and tests.

### Add Composite Tools

Composite tools belong under `tools/composite/` when they expose a higher-level action but still run inside the executor as one registered tool.

Composite tools should be composed from lower-layer capabilities such as:

- deterministic tools in `tools/traditional/`,
- vision tools in `tools/vision/`,
- generative tools in `tools/edit/`.

For example, `replace_background` is implemented as:

```text
segment_subject -> generate_image -> blend_subject
```

It creates a subject mask, generates a replacement background, then composites the original subject over that generated background. This preserves the high-level action name while keeping the implementation inspectable as a sequence of lower-level operations.

Use composite tools for stable user-facing actions such as:

- `replace_background`
- `remove_object`
- `relight_subject`
- `make_product_cutout`

Do not hide long multi-step agent loops inside a composite tool. If a task needs planning, reflection, and replanning, it belongs in `workflow/`.

The current `replace_background` implementation is architecturally composite, but its quality is bounded by the current bootstrap `segment_subject` mask. Replacing that mask with a detector/SAM-backed implementation should improve composite output without changing the composite tool contract.

### Keep Generic Tools From Swallowing the Plan

Broad tools such as `edit_image` can technically perform many semantic edits. The planner should still prefer specialized tools when they exist, because specialized tools provide clearer intent, better traces, and narrower prompts.

Current policy:

- decompose multi-intent requests into separate steps when registered tools support the separate intents,
- choose the most specific registered tool whose capability description matches each intent,
- use broad fallback tools only when no specific registered tool fits, or when the request explicitly requires one integrated semantic edit.

When adding a broad generative tool, update its `ToolSpec.description` so contributors understand its proper scope. Keep `prompts/planner.md` limited to architecture-level planning rules rather than project-member preferences about specific subjects or styles.

## Testing Strategy

For every change:

```bash
pytest -q
ruff check .
```

For live provider changes:

```bash
RUN_LIVE_AGENT_TESTS=1 pytest tests/test_live_integration.py -q -s
```

Default tests should not require Gemini, FLUX, GPU, network, or API keys.

Use live tests for actual provider behavior. Do not fake Gemini planning or FLUX editing when the purpose is to validate integration.

## Design Rules

- Keep provider-specific code in `models/`.
- Keep workflow orchestration provider-neutral.
- Keep tool actions registered through `ToolRegistry`.
- Keep prompts editable and separate from Python logic.
- Keep schemas strict enough to validate model output.
- Avoid parallel `v1`, `v2`, `legacy`, or `new` implementations.
- Add tests for every changed behavior.

## Common Tasks

### List Registered Tools

```python
from tools import create_default_tool_registry

registry = create_default_tool_registry()
print(registry.specs_markdown())
```

### Run One Agent Request

```bash
python app.py \
  --image test_img/stand_female_0.jpg \
  --prompt "Use the replace_background tool to change the background to a sunny beach."
```

The default console output is a structured trajectory. It includes:

- run inputs,
- each iteration,
- planner goal, assumptions, constraints, notes, and steps,
- compiled tool mappings,
- tool call names and arguments,
- produced artifact aliases and paths,
- evaluator score, satisfaction flag, missing requirements, and suggestions.

Use JSON-lines output when another process will consume the trace:

```bash
python app.py \
  --trace-format json \
  --image test_img/stand_female_0.jpg \
  --prompt "Use the replace_background tool to change the background to a sunny beach."
```

Use quiet output when only the final summary is wanted:

```bash
python app.py \
  --trace-format none \
  --image test_img/stand_female_0.jpg \
  --prompt "Use the replace_background tool to change the background to a sunny beach."
```

### Force A Replanning Trajectory

For debugging loop behavior, the app can intentionally weaken only the first background replacement pass:

```bash
python app.py \
  --trace-format plain \
  --max-iterations 3 \
  --debug-disable-refine-first-iteration \
  --image test_img/stand_female_1.jpg \
  --prompt "Change the background to a sunny beach."
```

This leaves production behavior unchanged. On iteration 0, `replace_background` runs only:

```text
segment_subject -> generate_image -> blend_subject
```

The refinement substep is enabled again on later iterations:

```text
segment_subject -> generate_image -> blend_subject -> edit_image_refine
```

Use this mode to verify that the evaluator can reject a weak first result and that the planner can replan with previous actions and feedback in state.

### Inspect Outputs

Look under:

- `outputs/images/`
- `outputs/masks/`
- `outputs/logs/`
- `outputs/plans/`

### Debug Planner Output

Open the latest file in `outputs/plans/`. If the planner emits an unknown action or missing args, the compiler should fail explicitly with a tool/action validation error.

### Debug State

Open the latest file in `outputs/logs/`. It contains current image path, artifact aliases, action history, and evaluator reports.

## Future Improvements

Recommended next steps:

1. Replace the bootstrap segmentation tool with a real detector/SAM implementation behind the same registry boundary.
2. Add typed per-tool argument schemas for stronger validation and better planner feedback.
3. Add retry policy around individual tool failures.
4. Add evaluator-specific replanning policies, such as "try deterministic correction first" or "stop after semantic mismatch."
5. Add persistent trajectory memory once repeated user sessions need retrieval.
6. Add an optional DAG executor when plans require parallel independent tools.
