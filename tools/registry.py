from __future__ import annotations

from collections.abc import Iterable

from tools.base import ImageTool
from tools.composite.replace_background import ReplaceBackgroundTool
from tools.edit.image_edit import ChangePoseTool, GenerateImageTool, ImageEditTool
from tools.traditional.blend import BlendSubjectTool
from tools.traditional.blur import BlurTool
from tools.traditional.crop import CropTool
from tools.traditional.resize import ResizeTool
from tools.traditional.rotate import RotateTool
from tools.traditional.sharpen import SharpenTool
from tools.vision.caption import ImageMetadataTool
from tools.vision.segment import SegmentSubjectTool


class ToolRegistry:
    def __init__(self, tools: Iterable[ImageTool] | None = None) -> None:
        self._tools: dict[str, ImageTool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ImageTool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> ImageTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._tools))
            raise KeyError(f"Unknown tool action {name!r}. Available tools: {available}") from exc

    def specs_markdown(self) -> str:
        lines: list[str] = []
        for spec in sorted((tool.spec for tool in self._tools.values()), key=lambda item: item.name):
            params = ", ".join(
                f"{param.name}{'*' if param.required else ''}: {param.type}"
                for param in spec.parameters
            )
            lines.append(f"- {spec.name} [{spec.layer}]: {spec.description}. Args: {params or 'none'}")
        return "\n".join(lines)

    def names(self) -> set[str]:
        return set(self._tools)


def create_default_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ResizeTool(),
            CropTool(),
            RotateTool(),
            BlurTool(),
            SharpenTool(),
            BlendSubjectTool(),
            SegmentSubjectTool(),
            ImageMetadataTool(),
            GenerateImageTool(),
            ChangePoseTool(),
            ImageEditTool(),
            ReplaceBackgroundTool(),
        ]
    )
