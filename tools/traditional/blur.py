from __future__ import annotations

from PIL import ImageFilter

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult
from utils.image import open_image, save_png


class BlurTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="blur",
            layer=ToolLayer.TRADITIONAL,
            description="Apply Gaussian blur to an image.",
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="radius", type="number", required=True),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        source = context.state.resolve_path(action.args.get("image"))
        radius = float(action.args["radius"])
        if radius < 0:
            raise ValueError("blur radius must be non-negative")
        with open_image(source) as image:
            blurred = image.convert("RGB").filter(ImageFilter.GaussianBlur(radius=radius))
        out = save_png(blurred, context.output_path(action))
        return ToolResult(artifact_kind="image", path=out)
