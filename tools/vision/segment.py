from __future__ import annotations

from schemas.action import ActionSpec
from schemas.tool import ToolLayer, ToolParameter, ToolSpec
from tools.base import ToolContext, ToolResult
from utils.image import open_image, save_png
from utils.mask import centered_ellipse_mask, full_mask, full_subject_mask


class SegmentSubjectTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="segment_subject",
            layer=ToolLayer.VISION,
            description=(
                "Create a bootstrap subject mask. Use mode='center_ellipse' for a rough centered "
                "subject mask, mode='full' for broader full-subject coverage, or mode='whole_image' "
                "when an edit should apply to the entire image."
            ),
            parameters=[
                ToolParameter(name="image", type="artifact_or_path", required=False),
                ToolParameter(name="target", type="string", required=False, default="subject"),
                ToolParameter(name="mode", type="string", required=False, default="center_ellipse"),
            ],
            produces="mask",
        )

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        source = context.state.resolve_path(action.args.get("image"))
        mode = str(action.args.get("mode", "center_ellipse"))
        with open_image(source) as image:
            if mode == "whole_image":
                mask = full_mask(image.size)
            elif mode == "full":
                mask = full_subject_mask(image.size)
            elif mode == "center_ellipse":
                mask = centered_ellipse_mask(image.size)
            else:
                raise ValueError(
                    "segment_subject mode must be 'center_ellipse', 'full', or 'whole_image'"
                )
        out = save_png(mask, context.mask_path(action))
        return ToolResult(
            artifact_kind="mask",
            path=out,
            data={"target": str(action.args.get("target", "subject")), "mode": mode},
        )
