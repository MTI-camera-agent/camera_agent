from __future__ import annotations

from PIL import Image

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult
from utils.image import open_image, save_png


class ResizeTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="resize",
            layer=ToolLayer.TRADITIONAL,
            description="Resize an image to explicit width and height.",
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="width", type="integer", required=True),
                ToolParameter(name="height", type="integer", required=True),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        source = context.state.resolve_path(action.args.get("image"))
        width = int(action.args["width"])
        height = int(action.args["height"])
        if width <= 0 or height <= 0:
            raise ValueError("resize width and height must be positive")
        with open_image(source) as image:
            resized = image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
        out = save_png(resized, context.output_path(action))
        return ToolResult(artifact_kind="image", path=out)
