# CameraAgent — Ubiquitous Language

One-line: AI 拍照助手 MVP，纵切「景点打卡」— 预览帧 + 意图 → Plan → 粗调/精调 → 快门。

This file is a **glossary only**. Behavior specs live in `openspec/specs/`; milestones in `docs/01`; decisions in `docs/adr/`.

## Language

**ShootingPlan**:
Structured plan after intent confirmation: coarse guidance, edit instruction, and metadata for the act loop.
_Avoid_: plan JSON, shooting json

**reference_preview**:
Pre-capture target reference image (PIP), generated from edit instruction — not post-edit retouching.
_Avoid_: preview image, mockup, 示意图文件

**Question**:
Intent-clarification step before Plan; 1–2 confirmation questions from the main agent.
_Avoid_: chat, 追问

**coarseGuidance** / **fineGuidance**:
Machine-facing guidance for coarse (机位/站位) vs fine (姿态对齐) act phases.
_Avoid_: advice text only (when referring to structured overlay channel)

**vision_bridge**:
HTTP call from text-only structured agent to local VLM for image understanding.
_Avoid_: VLM proxy, image bridge

**Skill**:
Domain capability unit behind registry/factory (e.g. scene describe, reference image gen).
_Avoid_: tool (when meaning domain skill, not tools/registry Layer tool)

**Harness**:
Loop orchestration — shooting_loop / image_loop, memory hooks, skill registry — not model weights.

**Act loop**:
Plan → analyze frame → evaluate → replan or complete within a shooting session.
