from __future__ import annotations

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult
from utils.image import open_image, save_png


class CropTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="crop",
            layer=ToolLayer.TRADITIONAL,
            description="Crop an image using x, y, width, and height pixels.",
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="x", type="integer", required=True),
                ToolParameter(name="y", type="integer", required=True),
                ToolParameter(name="width", type="integer", required=True),
                ToolParameter(name="height", type="integer", required=True),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        source = context.state.resolve_path(action.args.get("image"))
        x = int(action.args["x"])
        y = int(action.args["y"])
        width = int(action.args["width"])
        height = int(action.args["height"])
        if width <= 0 or height <= 0:
            raise ValueError("crop width and height must be positive")
        with open_image(source) as image:
            cropped = image.convert("RGB").crop((x, y, x + width, y + height))
        out = save_png(cropped, context.output_path(action))
        return ToolResult(artifact_kind="image", path=out)
