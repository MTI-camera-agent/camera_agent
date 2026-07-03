# Contributor Guidelines

## Engineering Checklist
- [ ] **Model-agnostic architecture:** Keep all code 100% provider-neutral. Instantiate `agno` Agents, Executors, models, and tools only through factories, registries, or configuration layers.
- [ ] **No hardcoded providers:** Never bake in model names, vendors, API endpoints, credentials, or routing assumptions such as Gemini, Qwen, Flux, OpenAI, or local-only backends.
- [ ] **Pythonic by default:** Write idiomatic Python with clear modules, explicit names, small functions, and strict type hints on public and nontrivial internal interfaces.
- [ ] **OOP with boundaries:** Encapsulate responsibilities behind interfaces/protocols. Keep tools, prompts, orchestration, persistence, and domain logic decoupled.
- [ ] **Quality over cost:** Prefer simple, robust, scalable, maintainable designs over speed hacks, cheap shortcuts, or temporary convenience.
- [ ] **No version bloat:** Do not keep parallel implementations like `tool_v1.py`, `tool_v2.py`, `new_agent.py`, or `legacy_agent.py`. Replace, migrate, and delete.
- [ ] **Test every change:** Add or update unit, integration, regression, and fixture coverage for each feature, bug fix, or behavior change.
- [ ] **Verify E2E trajectories:** Continuously run end-to-end agent trajectory checks for planning, tool use, execution, recovery, and final output quality.
- [ ] **Protect regressions:** Every fixed bug needs a failing test first or a documented regression case that proves it stays fixed.
- [ ] **Fail explicitly:** Surface configuration, provider, tool, and runtime errors with actionable messages. Silent fallbacks are defects.
- [ ] **Keep reviews strict:** Reject changes that increase coupling, hide provider assumptions, duplicate behavior, skip tests, or trade maintainability for velocity.
