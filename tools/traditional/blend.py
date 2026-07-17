from __future__ import annotations

from PIL import Image, ImageFilter, ImageOps

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult
from utils.image import open_image, save_png


class BlendSubjectTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="blend_subject",
            layer=ToolLayer.TRADITIONAL,
            description=(
                "Composite a foreground image over a background image using a subject mask. "
                "White mask pixels keep the foreground; black mask pixels use the background."
            ),
            parameters=[
                ToolParameter(name="foreground", type="artifact_or_path", required=True),
                ToolParameter(name="background", type="artifact_or_path", required=True),
                ToolParameter(name="mask", type="artifact_or_path", required=True),
                ToolParameter(name="mask_blur_radius", type="number", required=False, default=2.0),
            ],
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        foreground_path = context.state.resolve_path(action.args["foreground"])
        background_path = context.state.resolve_path(action.args["background"])
        mask_path = context.state.resolve_path(action.args["mask"])
        mask_blur_radius = float(action.args.get("mask_blur_radius", 2.0))
        if mask_blur_radius < 0:
            raise ValueError("mask_blur_radius must be non-negative")

        with (
            open_image(foreground_path) as foreground_image,
            open_image(background_path) as background_image,
            open_image(mask_path) as mask_image,
        ):
            foreground = foreground_image.convert("RGB")
            background = ImageOps.fit(
                background_image.convert("RGB"),
                foreground.size,
                method=Image.Resampling.LANCZOS,
            )
            mask = mask_image.convert("L").resize(
                foreground.size,
                Image.Resampling.LANCZOS,
            )
            if mask_blur_radius:
                mask = mask.filter(ImageFilter.GaussianBlur(radius=mask_blur_radius))
            blended = foreground.copy()
            blended.paste(background, mask=ImageOps.invert(mask))

        out = save_png(blended, context.output_path(action))
        return ToolResult(artifact_kind="image", path=out)
