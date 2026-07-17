from __future__ import annotations

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult


class GenerateImageTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="generate_image",
            layer=ToolLayer.GENERATIVE,
            description="Generate a new image from a text prompt using the configured image service.",
            parameters=[
                ToolParameter(name="prompt", type="string", required=True),
                ToolParameter(name="size", type="string", required=False, default="1024x1024"),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        generator = context.services.get("image_generator")
        if generator is None:
            raise RuntimeError("No image_generator service is configured")
        out = context.output_path(action)
        generator.generate(
            prompt=str(action.args["prompt"]),
            output_path=out,
            size=str(action.args.get("size", "1024x1024")),
        )
        return ToolResult(artifact_kind="image", path=out)


class ImageEditTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="edit_image",
            layer=ToolLayer.GENERATIVE,
            description=(
                "General fallback image edit using the configured image editing service. "
                "Use this for one focused semantic edit when no more specific registered "
                "tool fits. Prefer specialized tools such as change_pose and "
                "replace_background when they match the requested operation."
            ),
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="prompt", type="string", required=True),
                ToolParameter(name="size", type="string", required=False, default="auto"),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        generator = context.services.get("image_generator")
        if generator is None:
            raise RuntimeError("No image_generator service is configured")
        source = context.state.resolve_path(action.args.get("image"))
        out = context.output_path(action)
        generator.edit(
            image_path=source,
            prompt=str(action.args["prompt"]),
            output_path=out,
            size=str(action.args.get("size", "auto")),
        )
        return ToolResult(artifact_kind="image", path=out)


class ChangePoseTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="change_pose",
            layer=ToolLayer.GENERATIVE,
            description=(
                "Change the main subject pose while preserving identity, clothing, "
                "camera perspective, and the current background as much as possible. "
                "Use for explicit pose changes such as standing to sitting."
            ),
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="target_pose", type="string", required=True),
                ToolParameter(name="preserve_prompt", type="string", required=False),
                ToolParameter(name="size", type="string", required=False, default="auto"),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        generator = context.services.get("image_generator")
        if generator is None:
            raise RuntimeError("No image_generator service is configured")
        source = context.state.resolve_path(action.args.get("image"))
        target_pose = str(action.args["target_pose"])
        preserve = str(
            action.args.get(
                "preserve_prompt",
                "Preserve the subject identity, face, hairstyle, clothing, body proportions, lighting, background, and camera perspective.",
            )
        )
        prompt = (
            f"{preserve} Change only the main subject pose to: {target_pose}. "
            "Avoid unrelated changes that are not required by the requested pose edit."
        )
        out = context.output_path(action)
        generator.edit(
            image_path=source,
            prompt=prompt,
            output_path=out,
            size=str(action.args.get("size", "auto")),
        )
        return ToolResult(artifact_kind="image", path=out, data={"prompt": prompt})
