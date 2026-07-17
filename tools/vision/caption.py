from __future__ import annotations

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult
from utils.image import open_image


class ImageMetadataTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="image_metadata",
            layer=ToolLayer.VISION,
            description="Record deterministic image metadata such as size, mode, and format.",
            parameters=[ToolParameter(name="image", type="artifact_or_path", required=False)],
            produces="metadata",
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        source = context.state.resolve_path(action.args.get("image"))
        with open_image(source) as image:
            data = {
                "path": str(source),
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "format": image.format,
            }
        return ToolResult(artifact_kind="metadata", data=data)
