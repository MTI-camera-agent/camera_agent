from __future__ import annotations

import re

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ImageTool, ToolContext, ToolResult
from tools.edit.image_edit import GenerateImageTool, ImageEditTool
from tools.traditional.blend import BlendSubjectTool
from tools.vision.segment import SegmentSubjectTool


class ReplaceBackgroundTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="replace_background",
            layer=ToolLayer.COMPOSITE,
            description=(
                "Composite high-level background replacement skill. It creates a subject mask, "
                "generates a new background image, and blends the original subject over the new "
                "background. Use when the requested edit is specifically background replacement."
            ),
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="background_prompt", type="string", required=True),
                ToolParameter(name="target", type="string", required=False, default="subject"),
                ToolParameter(
                    name="preserve_prompt",
                    type="string",
                    required=False,
                    description=(
                        "Optional compatibility metadata. Subject preservation is performed "
                        "through masking and compositing."
                    ),
                ),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        source = context.state.resolve_path(action.args.get("image"))
        output_alias = action.output or action.action
        background_prompt = str(action.args["background_prompt"])
        requested_mask_mode = str(action.args.get("mask_mode", "full"))
        mask_mode = _normalize_mask_mode(requested_mask_mode)
        requested_background_size = str(action.args.get("background_size", "1024x1024"))
        background_size = _normalize_background_size(requested_background_size)
        background_generation_prompt = (
            f"{background_prompt}. Create only the replacement background scene, "
            "without the foreground subject."
        )
        refine_requested = _as_bool(action.args.get("refine", True))
        refine_disabled_reason: str | None = None
        if context.execution_options.disable_replace_background_refine(context.state.iteration):
            refine_enabled = False
            refine_disabled_reason = "debug_disable_refine_first_iteration"
        else:
            refine_enabled = refine_requested
        substep_total = 4 if refine_enabled else 3

        mask_action = ActionSpec(
            action="segment_subject",
            args={
                "image": str(source),
                "target": str(action.args.get("target", "subject")),
                "mode": mask_mode,
            },
            output=f"{output_alias}_subject_mask",
        )
        mask_result = _run_substep(
            parent_action=action.action,
            index=1,
            total=substep_total,
            tool=SegmentSubjectTool(),
            action=mask_action,
            context=context,
        )
        if mask_result.path is None:
            raise RuntimeError("replace_background could not create a subject mask")

        background_action = ActionSpec(
            action="generate_image",
            args={
                "prompt": background_generation_prompt,
                "size": background_size,
            },
            output=f"{output_alias}_generated_background",
        )
        background_result = _run_substep(
            parent_action=action.action,
            index=2,
            total=substep_total,
            tool=GenerateImageTool(),
            action=background_action,
            context=context,
        )
        if background_result.path is None:
            raise RuntimeError("replace_background could not generate a replacement background")

        blend_action = ActionSpec(
            action="blend_subject",
            args={
                "foreground": str(source),
                "background": str(background_result.path),
                "mask": str(mask_result.path),
                "mask_blur_radius": float(action.args.get("mask_blur_radius", 2.0)),
            },
            output=(
                f"{output_alias}_deterministic_composite"
                if refine_enabled
                else output_alias
            ),
        )
        blend_result = _run_substep(
            parent_action=action.action,
            index=3,
            total=substep_total,
            tool=BlendSubjectTool(),
            action=blend_action,
            context=context,
        )
        if blend_result.path is None:
            raise RuntimeError("replace_background could not blend the subject and background")

        final_path = blend_result.path
        refine_prompt: str | None = None
        substeps = [
            "segment_subject",
            "generate_image",
            "blend_subject",
        ]
        if refine_enabled:
            preserve = str(
                action.args.get(
                    "preserve_prompt",
                    "Preserve the main subject identity, clothing, pose, foreground details, and camera perspective.",
                )
            )
            refine_prompt = (
                f"{preserve} Cleanly replace any remaining original background or mask boundary "
                f"artifacts with this background: {background_prompt}. Keep the result natural."
            )
            refine_action = ActionSpec(
                action="edit_image",
                args={
                    "image": str(blend_result.path),
                    "prompt": refine_prompt,
                    "size": "auto",
                },
                output=output_alias,
            )
            refine_result = _run_substep(
                parent_action=action.action,
                index=4,
                total=substep_total,
                tool=ImageEditTool(),
                action=refine_action,
                context=context,
            )
            if refine_result.path is None:
                raise RuntimeError("replace_background could not refine the composite")
            final_path = refine_result.path
            substeps.append("edit_image_refine")

        return ToolResult(
            artifact_kind="image",
            path=final_path,
            data={
                "substeps": substeps,
                "mask_path": str(mask_result.path),
                "background_path": str(background_result.path),
                "deterministic_composite_path": str(blend_result.path),
                "background_prompt": background_prompt,
                "background_generation_prompt": background_generation_prompt,
                "refine_prompt": refine_prompt,
                "refine_requested": refine_requested,
                "refine_enabled": refine_enabled,
                "refine_disabled_reason": refine_disabled_reason,
                "requested_mask_mode": requested_mask_mode,
                "mask_mode": mask_mode,
                "requested_background_size": requested_background_size,
                "background_size": background_size,
            },
        )


def _normalize_mask_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode in {"", "auto", "subject", "person", "center", "centered"}:
        return "full"
    if mode in {"center_ellipse", "full"}:
        return mode
    if mode in {"whole_image", "full_frame", "entire_image"}:
        return "whole_image"
    raise ValueError(
        "replace_background mask_mode must be 'center_ellipse', 'full', 'whole_image', or an auto/subject alias"
    )


def _normalize_background_size(value: str) -> str:
    size = value.strip().lower()
    if size in {"", "auto", "original", "source", "source_image", "match_source"}:
        return "1024x1024"
    if re.fullmatch(r"[1-9]\d*x[1-9]\d*", size):
        return size
    raise ValueError(
        "replace_background background_size must be WIDTHxHEIGHT, 'original', 'auto', or omitted"
    )


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _run_substep(
    *,
    parent_action: str,
    index: int,
    total: int,
    tool: ImageTool,
    action: ActionSpec,
    context: ToolContext,
) -> ToolResult:
    reporter = context.reporter
    if reporter is not None:
        reporter.composite_substep_started(
            parent_action=parent_action,
            index=index,
            total=total,
            action=action,
        )
    try:
        result = tool.run(action, context)
    except Exception as exc:
        if reporter is not None:
            reporter.composite_substep_failed(
                parent_action=parent_action,
                index=index,
                total=total,
                action=action,
                error=exc,
            )
        raise
    if reporter is not None:
        reporter.composite_substep_finished(
            parent_action=parent_action,
            index=index,
            total=total,
            action=action,
            artifact_kind=result.artifact_kind,
            artifact_path=result.path,
            data=result.data,
        )
    return result
