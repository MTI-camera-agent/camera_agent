from __future__ import annotations

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult
from utils.image import open_image, save_png


class RotateTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="rotate",
            layer=ToolLayer.TRADITIONAL,
            description="Rotate an image by degrees.",
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="degrees", type="number", required=True),
                ToolParameter(name="expand", type="boolean", required=False, default=True),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        source = context.state.resolve_path(action.args.get("image"))
        degrees = float(action.args["degrees"])
        expand = bool(action.args.get("expand", True))
        with open_image(source) as image:
            rotated = image.convert("RGB").rotate(degrees, expand=expand)
        out = save_png(rotated, context.output_path(action))
        return ToolResult(artifact_kind="image", path=out)
