# Camera Agent Documentation

Start here when navigating the project.

## Recommended Reading Order

1. [MVP 方案设计及计划](01-MVP期-方案设计及计划.md): five-phase product roadmap, **dual-service stack** (vLLM VLM + ComfyUI), API/schema, milestones.
2. [Development Workflow](development_workflow.md): Git, conda isolation, **mm-comfyui hard rules**, default start/stop (8000 + 8188).
3. [Project Guide](project_guide.md): architecture, module map, runtime flow, Agno usage, extension points, and current design tradeoffs.
4. [Pose And Hat Example](pose_hat_example.md): concrete successful trajectory from prompt to plan, tools, evaluation, and loop stop.
5. [Gemini VLM Example](gemini_vlm_example.md): standalone Gemini image-understanding example used as the initial reference.
6. [FLUX vLLM-Omni Service](flux_vllm_omni_service.md): **cold fallback** image service (`:8010`; not in default startup).
7. [服务器配置说明](服务器配置说明.md): 云端模型分工与常驻显存；**首选 A100 80GB**（5090 见附录）。
8. **[协作与规格驱动说明书](协作与规格驱动说明书.md)**: **团队日常操作手册** — OpenSpec/Pocock 指令、四角色流程、PR 规范、落地待办。
9. [协作与规格驱动工作流调研](协作与规格驱动工作流调研.md): 工具选型与探查依据（背景阅读）。
10. [Agent Skills 接入](agents/skills.md): `.cursor/skills` 与 `/opsx-*` 命令速查。

## Quick Commands

Run the default unit suite:

```bash
pytest -q
```

Run live integration tests with Gemini and FLUX:

```bash
RUN_LIVE_AGENT_TESTS=1 pytest tests/test_live_integration.py -q -s
```

Run the agent:

```bash
python app.py \
  --image test_img/stand_female_0.jpg \
  --prompt "Change the background to a sunny beach while preserving the person."
```
