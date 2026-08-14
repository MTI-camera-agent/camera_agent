# P3 执行计划 — Plan 双通道 Act（粗指引 overlay ∥ Qwen2511 示意图）

- **版本**：v1.1（2026-08-04）
- **状态**：Active — PR1 已实现未实测（待 App Phase A/C 真机实测）；PR2/PR3 todo
- **依据**：[01-MVP期-方案设计及计划.md](01-MVP期-方案设计及计划.md) §Phase 3 / §7 差距矩阵 / 附录 A / §12 App-Demo
- **范围**：把 `confirm-intent` 产出的 Plan 落地为两条并行 Act 通道；P3 只做到 `s1_coarse_act`，`s2_fine_act`/`s3_capture` 为 P4+

> 本文是**执行计划**（文件级交付 + PR 拆分 + 测试策略），设计 rationale 见主文档 §Phase 3。

---

## 1. 范围与 M3 验收

| 通道 | 内容 | 状态 |
|------|------|------|
| **A · 目标示意图** | Qwen2511（ComfyUI `:8188`）异步 `frame + editInstruction → reference_preview` PNG，前端 PIP | PR1 |
| **B · 粗调 overlay 循环** | `analyze-frame?phase=coarse_act` → cv-guide + composition-score + overlay-compose + plan-deviation | PR2 |

**M3 验收**：
- [ ] ① confirm-intent 后粗调 overlay 与 Plan 同步显示（PR2）
- [ ] ② Qwen2511 示意图异步到达，PIP 可预览（PR1）
- [ ] ③ analyze-frame 粗调阶段返回 `compositionScore`、`planDeviation`（PR2）
- [ ] ④ 连续 5 帧 score<0.35 触发 `severe`（PR2）

## 2. 现状 → 缺口（逐文件）

| 关注点 | 现状 | P3 缺口 |
|---|---|---|
| 契约 | [schemas/shooting.py](../schemas/shooting.py) 已有 `GuidanceLayer`/`GuidanceOverlayPayload`/`ShootingPlanStep`/`ReferencePreviewPayload` | 缺 `CompositionScore`、`VlmAlignScore`(P4 占位)、`AnalyzeFrameRequest/Response`、`progressScore`/`captureReady` |
| 慢路径 | [workflow/shooting_loop.py](../workflow/shooting_loop.py) 仅 `collect_intent_phase` + `confirm_and_plan` | 缺 `analyze_frame(phase=coarse_act)`（PR2） |
| 网关 | [routes/sessions.py](../services/gateway/routes/sessions.py) 有 submit/confirm/GET；confirm 把 preview 写成 `generating` stub | 缺 `POST analyze-frame`（PR2）、`GET reference-preview` + `GET reference-preview.png`（PR1）、异步任务器（PR1） |
| 图像客户端 | [comfyui_image.py](../models/comfyui_image.py) 同步 `edit()` 已通；[image_generation.py](../models/image_generation.py) FLUX `:8010` 冷备选 | 两者可直接复用；缺拍照域 skill 包装 + preserve-identity prompt 强约束（PR1） |
| 参考 | [vlm_edit_qwen3vl_qwen2511.py](../scripts/vlm_edit_qwen3vl_qwen2511.py) 已验证链路 | P3 的 instruction 直接用 planner 的 `editInstruction`，无需再调 VLM |
| Skill | 仅 [qwen3vl_photo.py](../skills/qwen3vl_photo.py) | 缺 `reference-image-qwen2511`(P0)、`reference-image-flux`(P1)、`cv-guide`(P1)、`overlay-compose`(P1)、`composition-score`(P2)、`plan-deviation`(P1) |
| 前端 | [app.js](../frontend/web/app.js)/[index.html](../frontend/web/index.html) 仅 S0/S1/S2（H5 降级为 parity） | 缺 S3（Plan+overlay 同步）、S4（粗调送帧循环）、S4'（PIP 示意图）——**改落 `mobile/`（Expo App）**，实时取景需 App，H5 不支持（见主文档 §12） |
| 配置 | [config.yaml](../config.yaml) `image_generator`(comfyui)/`image_generator_fallback`(flux) 已就位 | 加 `gateway.previews_dir`、`shooting.reference_preview` 块 |
| 依赖 | [requirements.txt](../requirements.txt) 无 OpenCV/numpy | cv-guide/composition-score 用 **OpenCV**（决策①），PR2 加入 |

## 3. 架构：双通道数据流

```text
confirm-intent (sync, fast return)
  ├─ 通道A：ReferencePreviewService.kickoff(sid, frame, editInstruction, previewId)
  │     └─ daemon Thread → ReferenceImageSkill.generate()
  │           ├─ primary: ComfyUIImageEditClient.edit()  HTTP :8188
  │           └─ fallback(可选): OpenAICompatibleImageClient.edit() :8010
  │           → 写 outputs/reference_previews/{sid}/{previewId}.png + .json(latency)
  │           → store: generating → ready/failed
  │     前端轮询 GET /reference-preview → ready 后 <img src=reference-preview.png>（PIP）
  └─ 通道B（首帧 overlay 即返回，PR2）：ShootingLoop.analyze_frame(coarse_act)
        └─ cv-guide + composition-score + overlay-compose + plan-deviation
        → AnalyzeFrameResponse{compositionScore, planDeviation, guidanceOverlay, progressScore}
   S4 循环（PR2）：前端 2fps/按钮取帧 → POST analyze-frame → 画 overlay + 分数 + severe 横幅
```

**不变量**（沿用主文档）：① ComfyUI 只走 HTTP，不进 VLM、不同进程双加载；② Agent 不做 GPU 调度，只注入 HTTP 客户端；③ 示意图 prompt 强制「保持身份与背景，不得臆造新元素」；④ 粗调循环纯确定性 CV（<100ms、无 GPU、可单测），MiniCPM 留给 P4。

## 4. 交付物清单（按层 + 精确路径）

### Schemas（PR1 最小 + PR2 补全）
- [schemas/shooting.py](../schemas/shooting.py)：PR1 仅确认 `ReferencePreviewPayload` 足够（已存在）；PR2 加 `CompositionScore`/`VlmAlignScore`(P4 占位)/`AnalyzeFrameRequest`/`AnalyzeFrameResponse`。

### Skills
- [skills/reference_image.py](../skills/reference_image.py)（PR1）：**一个类 `ReferenceImageSkill(client, generator)`**，包任意 `ImageGenerationClient.edit()`；`generate(frame, editInstruction, out) -> (path, latency_ms, w, h)`；强制 `PRESERVE_IDENTITY_SUFFIX`。两个 Skill ID（`reference-image-qwen2511`/`reference-image-flux`）= 同一类按 generator 实例化两次。
- [skills/cv_guide.py](../skills/cv_guide.py)（PR2）：OpenCV 人脸/人体检测 + 三分线 + `offset_ok` → 主体 bbox + advice。
- [skills/composition_score.py](../skills/composition_score.py)（PR2）：三分位/留白/地平线/主体大小启发式 → 0-1 + issues + suggestions。
- [skills/overlay_compose.py](../skills/overlay_compose.py)（PR2）：cv-guide + Plan 目标区 → `GuidanceOverlayPayload.layers`（前端 canvas 渲染）。
- [skills/plan_deviation.py](../skills/plan_deviation.py)（PR2）：策略表（5 帧<0.35 / bbox IoU<0.2×3 / 人脸消失>3s → severe）。

### Workflow
- [workflow/shooting_loop.py](../workflow/shooting_loop.py)（PR2）：加 `analyze_frame(*, phase, frame_path, annotations=None)`；coarse_act 走 CV 四件套，fine_act 抛 `NotImplementedError`(P4)。skills 经构造注入（保持 provider-neutral、可 mock）。

### Gateway
- [services/gateway/reference_preview.py](../services/gateway/reference_preview.py)（PR1）：`ReferencePreviewService`（daemon Thread + Lock，仿 [session_store.py](../services/gateway/session_store.py)）；session_id → `PreviewRecord`（status/data_ref/w/h/latency_ms/generator/error）；写 `outputs/reference_previews/{sid}/`。
- [services/gateway/factory.py](../services/gateway/factory.py)（PR1）：加 `build_reference_preview_service(config)`（建 image_generator + 可选 fallback；workflow/schema 路径按 repo root 解析）。
- [services/gateway/deps.py](../services/gateway/deps.py)（PR1）：`GatewaySettings.previews_dir`、`get_reference_preview_service`。
- [services/gateway/main.py](../services/gateway/main.py)（PR1）：lifespan 建 preview service 挂 `app.state`。
- [services/gateway/routes/sessions.py](../services/gateway/routes/sessions.py)：
  - PR1：confirm-intent 改为真正 kickoff（替换当前 stub L178-186）；`GET /sessions/{id}/reference-preview`；`GET /sessions/{id}/reference-preview.png`（FileResponse）。
  - PR2：`POST /sessions/{id}/analyze-frame`（phase=coarse_act；fine_act 501）。
- [services/gateway/session_store.py](../services/gateway/session_store.py)：`SessionRecord.reference_preview`（PR1）、`coarse_history`/`plan_deviation`（PR2）。

### 前端
- [frontend/web/](../frontend/web/)（降为 parity only）：PR1 加 PIP 轮询（confirm 后 ~1.5s 轮询 `GET reference-preview`，ready→`<img>`，failed→红字）。
- `mobile/`（待建，Expo App，承载相机功能）：PR1 PIP 同上（`<Image>`）；PR2 加 S3 overlay canvas（取景预览层之上）+ S4 送帧循环 + severe 横幅。实时取景 overlay 需 App，H5 不支持（见主文档 §12）。

### 配置
- [config.yaml](../config.yaml)：`gateway.previews_dir`（默认 `outputs/reference_previews`）；`shooting.reference_preview`{`generator`, `fallback_generator`(默认空), `poll_interval_seconds`, `prompt_suffix`}。

## 5. PR 分阶段（决策②：分阶段 PR1→PR2→PR3）

| PR | 范围 | 文件 | 命中 M3 |
|---|---|---|---|
| **PR1** 通道A 示意图(P0) | `ReferenceImageSkill` + `ReferencePreviewService` + 3 路由 + 前端 PIP + config | 见上 | ② |
| **PR2** 通道B 粗调 loop(P1/P2) | OpenCV 入 requirements + `cv-guide`/`composition-score`/`overlay-compose`/`plan-deviation` + `ShootingLoop.analyze_frame` + `analyze-frame` 路由 + 前端 S3/S4（**落 `mobile/` App**，非 `frontend/web/`） | 见上 | ①③④ |
| **PR3** 文档+验收 | 本文档打磨 + 主文档 §8 M3 勾选 + live 集成测试（ComfyUI 真链路） | docs + tests/test_live_integration.py | M3 全过 |

### PR1 详细步骤
1. [skills/reference_image.py](../skills/reference_image.py)：`ReferenceImageSkill` + `PRESERVE_IDENTITY_SUFFIX`（取自 [qwen3vl_photo.py](../skills/qwen3vl_photo.py) 的 PHOTO_INSTRUCTION_PROMPT 约束段，确保复用一致措辞）。
2. [services/gateway/reference_preview.py](../services/gateway/reference_preview.py)：`ReferencePreviewService.kickoff/get/get_payload`；daemon Thread；失败时若配 `fallback_generator` 则重试并记录实际 generator。
3. [services/gateway/factory.py](../services/gateway/factory.py)：`build_reference_preview_service(config)`。
4. [services/gateway/deps.py](../services/gateway/deps.py)+[main.py](../services/gateway/main.py)：settings.previews_dir + lifespan 挂载。
5. [routes/sessions.py](../services/gateway/routes/sessions.py)：confirm-intent kickoff；GET reference-preview；GET reference-preview.png。
6. [session_store.py](../services/gateway/session_store.py)：`reference_preview` 字段。
7. [config.yaml](../config.yaml)：previews_dir + reference_preview 块。
8. [frontend/web/app.js](../frontend/web/app.js)+[index.html](../frontend/web/index.html)：PIP 轮询 + 显示。
9. tests：`tests/test_reference_preview.py`（mock image client → generating/ready/failed、prompt 含 preserve、fallback）；扩 `tests/test_gateway.py`（confirm kicks preview、GET 轮询序列、png 200/404）。

## 6. 测试策略（遵循 project_guide：默认测试不依赖 GPU/网络）

- **PR1**：mock `ImageGenerationClient`，断言 `generating→ready`、`data_ref` 落地、`latency_ms>0`、prompt 含 preserve 后缀、fallback 切换记录 generator；路由：confirm 后 preview=generating、轮询序列、serve PNG 200/404。默认测试不启 ComfyUI。
- **PR2**：PIL 生成确定性测试图跑 cv-guide/composition-score/plan-deviation；偏离策略表逐例（5 帧<0.35→severe 等）；`analyze-frame` mock skills。
- **live**：`RUN_LIVE_AGENT_TESTS=1` 跑 ComfyUI `:8188` 真 `editInstruction→PNG` 端到端（PR3）。

## 7. 锁定决策

| ID | 决策 | 选定 |
|----|------|------|
| ① CV 栈 | cv-guide/composition-score | **OpenCV**（`opencv-python`+`numpy` 入 requirements，PR2） |
| ② 节奏 | P3 范围 | **分阶段 PR1→PR2→PR3** |
| ③ 落地形式 | Plan 产出 | **写本文档 + 实施 PR1** |
| — 示意图交付 | 轮询 vs SSE | **轮询**（`GET reference-preview`，匹配 P2 HTTP 单帧 ethos；SSE 后议） |
| — 前端 overlay 渲染 | 服务端栅格 vs 前端 canvas | **前端 canvas 渲染 `GuidanceLayer`**（对应 P5 端侧 overlay 演进） |

## 8. 风险

| 风险 | 缓解 |
|------|------|
| Qwen2511 >30s | 粗调继续、preview 晚到；可临时切 FLUX（已配 `image_generator_fallback`） |
| 身份/背景漂移 | `ReferenceImageSkill` 强制 `PRESERVE_IDENTITY_SUFFIX` |
| 24GB 显存 | ComfyUI 与 VLM 串行互斥（运维约束，非代码；见 [development_workflow.md](development_workflow.md) §3.5） |
| 单 worker 进程内存 preview | `ReferencePreviewService` 进程内 + Lock；多 worker 部署后议 Redis（同 O6） |

---

*关闭本表项或 PR 合并时，更新主文档 [01-MVP期-方案设计及计划.md](01-MVP期-方案设计及计划.md) §8 M3 勾选并递增版本号。*
