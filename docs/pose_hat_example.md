# Example Trajectory: Sitting Pose And Hat

This document explains one successful run of the camera agent:

```bash
python app.py \
  --trace-format plain \
  --image test_img/stand_female_1.jpg \
  --prompt "Change the mainbody's pose from standing to sitting, then add a hat to the mainbody."
```

The run finishes in one iteration because the evaluator decides the generated image satisfies the request.

## 1. Runtime Setup

`app.py` loads `config.yaml`, builds the tool registry, constructs model clients, and creates the workflow loop.

The important runtime components are:

- `PlannerAgent`: Gemini VLM through the provider-neutral `StructuredVisionClient`.
- `ToolRegistry`: exposes registered tool capabilities to the planner as text.
- `PlanCompiler`: validates that planned actions map to real tools.
- `ToolExecutor`: executes the compiled Python tools.
- `ReflectorAgent`: Gemini VLM evaluator that compares original and final images.
- `StateManager`: stores plans and state snapshots under `outputs/`.

Note: `PerceptionAgent` exists in `agents/perception.py`, but the current `app.py` CLI does not call it as a separate stage. In this path, visual perception is performed inside the planner and reflector VLM calls.

## 2. Initial State

Input image:

```text
test_img/stand_female_1.jpg
```

User instruction:

```text
Change the mainbody's pose from standing to sitting, then add a hat to the mainbody.
```

The state manager creates an `ExecutionState`:

```text
original_image = /home/liujinyuan/Developer/camera_agent/test_img/stand_female_1.jpg
current_image  = /home/liujinyuan/Developer/camera_agent/test_img/stand_female_1.jpg
iteration      = 0
artifacts      = {}
history        = []
evaluations    = []
```

Built-in image aliases are available to tools:

- `original_image`: the initial input image.
- `current_image`: the latest image result.

## 3. Planning

The planner receives:

- the current image,
- the user prompt,
- the state summary,
- evaluator feedback, which is `None` in iteration 0,
- the registered tool catalog.

The tool catalog tells the planner that relevant tools include:

- `change_pose`: focused generative tool for pose changes.
- `edit_image`: generic fallback semantic image edit.

The planner returns a typed `Plan` with this goal:

```text
Change the main subject's pose from standing to sitting and add a hat.
```

The planner decomposes the request into two steps because the instruction has two distinct intents:

```text
1. change_pose -> sitting_pose_image
2. edit_image  -> final_image, requires sitting_pose_image
```

The plan is saved to:

```text
outputs/plans/plan_iter_00.json
```

## 4. Compilation

`PlanCompiler` checks the plan before execution:

- `change_pose` exists in `ToolRegistry`.
- `edit_image` exists in `ToolRegistry`.
- required arguments are present.
- `edit_image` depends on `sitting_pose_image`, which is produced by step 1.

After validation, the compiler produces two executable actions:

```text
step_1_tool: change_pose
step_2_tool: edit_image
```

## 5. Tool Execution

### Step 1: `change_pose`

Planner action:

```json
{
  "action": "change_pose",
  "output": "sitting_pose_image",
  "args": {
    "image": "original_image",
    "target_pose": "sitting",
    "preserve_prompt": "a young woman in a white blouse and beige skirt holding a fan, standing in a park",
    "size": "1024x1024"
  }
}
```

Runtime behavior:

- `original_image` resolves to the input file.
- `ChangePoseTool` builds a focused image-edit prompt.
- The FLUX image edit endpoint is called through `OpenAICompatibleImageClient`.
- The result is stored as an image artifact.

Output artifact:

```text
alias: sitting_pose_image
path:  outputs/images/iter_00_sitting_pose_image.png
```

The state updates:

```text
artifacts["sitting_pose_image"] = image artifact
current_image = outputs/images/iter_00_sitting_pose_image.png
```

### Step 2: `edit_image`

Planner action:

```json
{
  "action": "edit_image",
  "output": "final_image",
  "requires": ["sitting_pose_image"],
  "args": {
    "image": "sitting_pose_image",
    "prompt": "a young woman in a white blouse and beige skirt sitting in a park, wearing a stylish hat",
    "size": "1024x1024"
  }
}
```

Runtime behavior:

- `sitting_pose_image` resolves to the output from step 1.
- `ImageEditTool` calls the FLUX image edit endpoint.
- The edit adds a hat to the pose-edited image.

Output artifact:

```text
alias: final_image
path:  outputs/images/iter_00_final_image.png
```

The state updates again:

```text
artifacts["final_image"] = image artifact
current_image = outputs/images/iter_00_final_image.png
```

## 6. Evaluation

The reflector receives two images:

1. the original image,
2. the current final image.

It also receives the user request and state summary. It returns an `EvaluationReport`:

```text
satisfied: True
score: 1.00
summary: The agent successfully changed the subject's pose from standing to sitting and added a hat as requested. The image quality is high and the edits are well-integrated.
```

The state snapshot is saved to:

```text
outputs/logs/state_iter_00.json
```

## 7. Why The Loop Stops

`ImageLoop` checks the evaluator report:

```python
if report.satisfied:
    return LoopResult(...)
```

Because `satisfied=True`, the loop does not run iteration 1 or 2, even though `max_iterations=3`.

Final result:

```text
final_image = outputs/images/iter_00_final_image.png
satisfied   = True
```

## 8. What This Example Demonstrates

This run shows the intended control flow:

```text
Image + user prompt
  -> Planner VLM creates a typed plan
  -> Compiler validates tool calls
  -> Executor runs image tools sequentially
  -> Reflector VLM evaluates the result
  -> Loop stops because the result is satisfactory
```

It also shows why decomposition matters. The planner did not collapse the whole request into one generic edit. It used:

```text
change_pose first, then edit_image
```

That makes the trajectory easier to inspect and gives later replanning iterations useful state if the evaluator ever rejects the result.
