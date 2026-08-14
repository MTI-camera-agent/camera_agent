## Summary

<!-- What changed and why (1–3 sentences). Link openspec change if applicable. -->

- Openspec change: `openspec/changes/<change-id>/` (or N/A for hotfix)
- Role lane: SE / Harness / Model / Skills

## Spec / tasks

- [ ] Proposal and delta specs reviewed (SE approval for apply)
- [ ] All tasks in `tasks.md` completed or explicitly deferred
- [ ] `CONTEXT.md` / `docs/adr/` updated if terminology or decisions changed

## Test plan

```bash
pytest -q
# Optional live:
# RUN_LIVE_AGENT_TESTS=1 pytest tests/test_live_integration.py -q -s
```

- [ ] Unit tests added/updated for behavior change
- [ ] Manual smoke (gateway / CLI) if API or UI touched

## Eval (post-implement)

<!-- Brief: acceptance vs openspec scenarios; gaps; follow-ups -->

## Checklist

- [ ] No parallel `*_v2` / legacy duplicates ([AGENTS.md](../AGENTS.md))
- [ ] Provider-neutral via factories/registries
- [ ] `docs/01` or `p3_*` updated if milestone acceptance affected (SE)
