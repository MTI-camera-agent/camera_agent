from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from google import genai
from google.genai import types


DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_IMAGE = Path("test_img/stand_female_0.jpg")


@dataclass(frozen=True)
class ToolUseEvent:
    name: str
    detail: str | None = None


def create_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Run: export GEMINI_API_KEY='your-google-ai-studio-api-key'"
        )
    return genai.Client(api_key=api_key)


def ask_with_google_search(
    client: genai.Client,
    prompt: str,
    model: str = DEFAULT_MODEL,
    stream: bool = True,
) -> str:
    config = types.GenerateContentConfig(
        tools=[types.Tool(googleSearch=types.GoogleSearch())],
        temperature=0.2,
    )
    if stream:
        return _stream_generate_content(
            client=client,
            model=model,
            contents=prompt,
            config=config,
    )

    response = client.models.generate_content(model=model, contents=prompt, config=config)
    _emit_tool_use_events(response, seen=set())
    text = response.text or ""
    print(text)
    return text


def describe_image(
    client: genai.Client,
    image_path: Path,
    prompt: str,
    model: str = DEFAULT_MODEL,
    stream: bool = True,
) -> str:
    image = types.Part.from_bytes(
        data=image_path.read_bytes(),
        mime_type=_guess_mime_type(image_path),
    )
    contents = [prompt, image]
    config = types.GenerateContentConfig(temperature=0.2)
    if stream:
        return _stream_generate_content(
            client=client,
            model=model,
            contents=contents,
            config=config,
        )

    response = client.models.generate_content(model=model, contents=contents, config=config)
    text = response.text or ""
    print(text)
    return text


def _stream_generate_content(
    client: genai.Client,
    model: str,
    contents: object,
    config: types.GenerateContentConfig,
) -> str:
    chunks: list[str] = []
    seen_tools: set[tuple[str, str | None]] = set()
    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=config,
    ):
        _emit_tool_use_events(chunk, seen=seen_tools)
        text = chunk.text or ""
        if not text:
            continue
        chunks.append(text)
        print(text, end="", flush=True)
    print()
    return "".join(chunks)


def _emit_tool_use_events(response: types.GenerateContentResponse, seen: set[tuple[str, str | None]]) -> None:
    for event in _extract_tool_use_events(response):
        key = (event.name, event.detail)
        if key in seen:
            continue
        seen.add(key)
        if event.detail:
            print(f"\n[tool] used {event.name}: {event.detail}", file=sys.stderr, flush=True)
        else:
            print(f"\n[tool] used {event.name}", file=sys.stderr, flush=True)


def _extract_tool_use_events(response: types.GenerateContentResponse) -> Iterable[ToolUseEvent]:
    for candidate in response.candidates or []:
        yield from _extract_grounding_events(candidate)
        content = candidate.content
        if content is None:
            continue
        for part in content.parts or []:
            function_call = getattr(part, "function_call", None)
            if function_call is not None and function_call.name:
                yield ToolUseEvent(name=function_call.name, detail=_format_tool_args(function_call.args))

            tool_call = getattr(part, "tool_call", None)
            if tool_call is not None and tool_call.tool_type:
                yield ToolUseEvent(name=str(tool_call.tool_type), detail=_format_tool_args(tool_call.args))


def _extract_grounding_events(candidate: types.Candidate) -> Iterable[ToolUseEvent]:
    metadata = candidate.grounding_metadata
    if metadata is None:
        return

    queries = metadata.web_search_queries or metadata.image_search_queries or []
    for query in queries:
        yield ToolUseEvent(name="google_search", detail=f"query={query!r}")

    if not queries and metadata.grounding_chunks:
        yield ToolUseEvent(name="google_search", detail=f"sources={len(metadata.grounding_chunks)}")


def _format_tool_args(args: dict[str, Any] | None) -> str | None:
    if not args:
        return None
    return ", ".join(f"{key}={value!r}" for key, value in args.items())


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    raise ValueError(f"Unsupported image type: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gemini 2.5 Flash text and VLM examples.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming and print the response only after it completes.",
    )
    subparsers = parser.add_subparsers(dest="command")

    search = subparsers.add_parser("search")
    search.add_argument(
        "--prompt",
        default=(
            "Use Google Search to answer with current information: "
            "What are the latest official Gemini models available in Google AI Studio, "
            "and cite the sources you used?"
        ),
    )

    image = subparsers.add_parser("image")
    image.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    image.add_argument(
        "--prompt",
        default=(
            "Describe this image in detail. Include the main subject, pose, clothing, "
            "scene, lighting, and any details useful for image editing."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    client = create_client()

    if args.command == "search":
        ask_with_google_search(client, args.prompt, model=args.model, stream=not args.no_stream)
        return
    if args.command == "image":
        describe_image(client, args.image, args.prompt, model=args.model, stream=not args.no_stream)
        return

    print("=== Google Search Tool Example ===")
    ask_with_google_search(
        client,
        (
            "Use Google Search to answer with current information: "
            "What is one recent Gemini API update from Google AI Studio? "
            "Include source links."
        ),
        model=args.model,
        stream=not args.no_stream,
    )
    print("\n=== Image Understanding Example ===")
    describe_image(
        client,
        DEFAULT_IMAGE,
        (
            "Describe this image in detail. Include the main subject, pose, clothing, "
            "scene, lighting, and any details useful for image editing."
        ),
        model=args.model,
        stream=not args.no_stream,
    )


if __name__ == "__main__":
    main()
