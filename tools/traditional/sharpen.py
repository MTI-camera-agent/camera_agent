from __future__ import annotations

from PIL import ImageFilter

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult
from utils.image import open_image, save_png


class SharpenTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="sharpen",
            layer=ToolLayer.TRADITIONAL,
            description="Apply a sharpen filter to an image.",
            parameters=[ToolParameter(name="image", type="artifact_or_path", required=False)],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        source = context.state.resolve_path(action.args.get("image"))
        with open_image(source) as image:
            sharpened = image.convert("RGB").filter(ImageFilter.SHARPEN)
        out = save_png(sharpened, context.output_path(action))
        return ToolResult(artifact_kind="image", path=out)
