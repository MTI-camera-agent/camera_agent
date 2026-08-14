# Agent Skills（CameraAgent）

业务仓 **不复制** 整个 [`reference/skills`](../../reference/skills) 或 [`reference/openspec`](../../reference/openspec)。以下为已接入 Cursor 的技能与用法。

## OpenSpec（变更规格）

由 `openspec init` 安装，位于 [`.cursor/skills/openspec-*`](../../.cursor/skills/) 与 [`.cursor/commands/opsx-*.md`](../../.cursor/commands/)。

| 命令 / 技能 | 用途 |
|-------------|------|
| `/opsx-explore` | 读仓、澄清方案；**不写业务代码** |
| `/opsx-propose` | 创建 `openspec/changes/<id>/` 全套规划 artifact |
| `/opsx-apply` | 按 tasks 实现 |
| `/opsx-archive` | 归档 change，合入 `openspec/specs/` |

配置：[`openspec/config.yaml`](../../openspec/config.yaml)。

## mattpocock/skills（精选）

已复制到 [`.cursor/skills/`](../../.cursor/skills/)（来源 commit `84fdeff`）：

| 技能目录 | 触发 | 阶段 |
|----------|------|------|
| `grill-with-docs` | 用户显式 | A 实验 — 默认 |
| `grill-me` | 用户显式 | A 实验 — 非代码议题 |
| `grilling` | 被 grill-* 委托 | 访谈引擎 |
| `domain-modeling` | 被 grill-with-docs 委托 | 写 CONTEXT / ADR |
| `tdd` | apply 阶段 | D 实现 |
| `code-review` | PR 前 | D 评估 |
| `research` | 调研 | A 实验 |

完整上游列表见 [reference/skills/README.md](../../reference/skills/README.md)。更新精选技能：

```bash
SRC=reference/skills/skills
DST=.cursor/skills
for s in productivity/grill-me productivity/grilling engineering/grill-with-docs \
         engineering/domain-modeling engineering/tdd engineering/code-review engineering/research; do
  rm -rf "$DST/$(basename $s)"
  cp -r "$SRC/$s" "$DST/$(basename $s)"
done
cp reference/skills/skills/engineering/domain-modeling/*.md .cursor/skills/domain-modeling/
```

## 工作流顺序

1. `grill-with-docs`（可选）→ 术语进 [`CONTEXT.md`](../../CONTEXT.md)
2. `/opsx-propose <change-id>`
3. SE 整合评审（文档 PR）
4. `/opsx-apply` + `tdd` + `pytest`
5. `code-review` + `eval.md` + `/opsx-archive` + 代码 PR

详见 **[协作与规格驱动说明书.md](../协作与规格驱动说明书.md)** §7；背景见 [协作与规格驱动工作流调研.md](../协作与规格驱动工作流调研.md)。
