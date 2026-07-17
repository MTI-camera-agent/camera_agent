# Camera Agent Documentation

Start here when navigating the project.

## Recommended Reading Order

1. [Project Guide](project_guide.md): architecture, module map, runtime flow, Agno usage, extension points, and current design tradeoffs.
2. [Pose And Hat Example](pose_hat_example.md): concrete successful trajectory from prompt to plan, tools, evaluation, and loop stop.
3. [Gemini VLM Example](gemini_vlm_example.md): standalone Gemini image-understanding example used as the initial reference.
4. [FLUX vLLM-Omni Service](flux_vllm_omni_service.md): local image-generation and image-editing service reference.

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
