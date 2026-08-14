# CameraAgent iOS App — UX 设计说明

- **版本**：v3.1（2026-08-07）—— HUD 收拢变焦上方带 + 双击切换 + 气泡水平轮动 + Plan/提示合一 + 模拟控件外置
- **状态**：设计稿（未编码）；对应 [01-MVP期-方案设计及计划.md](../01-MVP期-方案设计及计划.md) §5 Phase 3–5 / §9.2 / 附录 A.4–A.5
- **可预览草稿**：[ios_app_ux_v3.html](ios_app_ux_v3.html)（v3.1，浏览器直接打开）；旧 [v2](ios_app_ux_v2.html) / [v1](ios_app_ux_v1.html) / [v0](ios_app_ux.html) 已被取代，保留作参考
- **视觉令牌**：沿用 [frontend/web/styles.css](../../frontend/web/styles.css)（ink/lake/mist + Fraunces/IBM Plex Sans）

> v3.1 修复 v3.0 的 7 处问题：① 所有 HUD 收拢到**变焦数字上方带状空白区**；② 机器人 **双击切换 L/R**（去 hover/拖动）；③ skill 气泡**水平全屏 + 溢出轮动**；④ Plan/提示**合一**（显 tip 或"✓某环节已完成"，不显全 Plan）+ 小圆点变色；⑤ 模拟控件**外置**侧边面板；⑥ `target_subject` bbox 移 preview **左侧小框**、小人**中间靠右**、目标图右、不重叠；⑦ 去掉 overlay 顶部提示文字（提示只在变焦上方带）。

> 注：本会话模型无图像视觉能力（Read PNG 返回空、inline 仅文本元数据）；v3.1 按用户 7 点文字描述实现，视觉细节（空白区精确边界等）待用户看渲染 HTML 后校正。

---

## 1. 三大场景 = 设计层分组（不进 UI）

| 分组 | 覆盖 skill |
|---|---|
| 给自己拍 | 分身入画（clone-self-into-scene） |
| 给他人拍 | 拍女朋友、拍孩子… |
| 拍风景 | 拍风景、拍古典建筑、拍美食、拍月亮… |

> 三大场景仅设计层划分，**不做 UI 选择器**。具体 skill 由端侧 VLM 扫描后按当前预览 match 白名单 + 可实现性，**水平气泡**供点选。分身入画为 skill（无独立开关）。

---

## 2. 设计原则（v3.1）

1. **相机即根屏**：相机 + chrome 始终在；机器人/HUD/overlay 均相机之上的层。
2. **不干扰取景**：所有 HUD（机器人/气泡/scan/listen/plan-tip）收拢于**变焦数字上方带状空白区**（`.hud-band`，`bottom:~104px`）；overlay 居中；无底部面板 sheet、无顶部提示。
3. **机器人即助手**：呼吸灯=在工作；短按=扫描；长按=语音；**双击=切换 L/R**（固定贴左/右）。
4. **skill 可实现性**：扫描后只显当前场景可做 skill（不可达灰显✗），含分身入画。
5. **Plan 轻约束 + 持续 Eval**：3~5 步、√推进、提示不约束、容差范围即完成、择机抓拍、中途跳走→提醒。
6. **Question 退场**：Intent 由 skill 点选或语音驱动；歧义由气泡轻问（非模态）。
7. **模拟控件外置**：Eval推进/severe/刷新/结束 等模拟按钮放侧边面板（手机外），手机 UI 内无模拟按钮。

---

## 3. 状态机（相机常驻根屏；hud-band = 变焦上方带）

```
camera ─(✦ on)─► robot_idle ─(✦ off)─► camera
robot_idle ─(短按)─► scanning(光效+"正在扫描") ─► skills(水平气泡) ─(点 skill)─► plan_active
robot_idle ─(长按)─► listening(呼吸"正在听"+波形) ─(松开)─► plan_active
robot_idle ─(双击)─► toggle L/R
plan_active = 相机 + hud-band[机器人 + plan/tip 合一 + 小圆点] + 中部 overlay(框/箭头/锚点/目标图)
   plan_active ─(端侧 VLM Eval)─► 步骤√ / overlay 演化 / 择机抓拍 capture
   plan_active ─(severe)─► severe_banner；─(场景失效)─► plan_refresh_modal；─(跳走/自行拍摄)─► end_remind
   plan_active ─(capture_ready)─► capture(3s)─► done ─► camera
```

---

## 4. 屏与布局（v3.1）

```
┌─────────────────────────────┐
│ statusbar / ✦开关            │
│  preview (cam)               │
│  ┌bbox(左,小)┐    ┌目标图PIP(右)┐
│  │target_subject│  │reference  │
│  小人(中间靠右, figX .62)          │
│ ── hud-band (变焦数字上方) ── │ ← 机器人 + 气泡/plan-tip + scan/listen
│  .5 1x 2 4 8  (zoom)         │
│ 快门⦿ · 翻转↻               │
└─────────────────────────────┘
侧边面板（手机外）：模拟控制 = [扫描][语音][Eval推进→][severe][Plan刷新][结束]
```

| 区/态 | 内容 |
|---|---|
| 顶栏 | 左⚡/◐；右 ✦ 开关（召唤/收起机器人） |
| 底部 chrome（常驻） | 变焦 `.5/1x/2/4/8` + 快门⦿ + 翻转↻ |
| **hud-band**（变焦上方带） | 机器人 icon（呼吸、双击换边）+ hud-fill（气泡/plan-tip/scan/listen） |
| robot_idle | 机器人 + hint"短按=扫描·长按=语音·双击=换边" |
| scanning | 预览光效/雷达 + "正在扫描中…"（带内） |
| skills | 机器人 + **水平全屏气泡行**（溢出轮动、hover 暂停）；可达高亮/不可达灰显✗ |
| listening | 机器人 + 波形 + "正在听…松开发送" |
| plan_active | 机器人 + **plan/tip 合一**（小圆点 + 文本：tip 或"✓X已完成"）+ 中部 overlay |
| capture | 就绪环 + 3s 倒计时 |
| done | 成片 + Plan 摘要 + 再拍/完成 |

### 4.1 机器人交互
- **呼吸灯**：CSS `breathe`（scale+光晕脉冲）；idle 慢、scan 快、listen 更快转 sun 色。
- **双击切换 L/R**：robot 固定贴左/右（`hud-band.L` row / `.R` row-reverse）；双击 toggle。**无拖动/hover**。
- **短按**（pointerup <500ms，且非双击）→ scanning。
- **长按**（≥500ms）→ listening → 松开 → plan_active。
- 三态判定：单击<500ms→扫描；两次单击<260ms→双击换边；按住≥500ms→语音。

### 4.2 气泡水平轮动
- `.bubbles`（flex:1、overflow hidden、左右渐隐 mask）；`.bub-track`（width:max-content、`marq` 18s 线性、translateX 0→-50%、内容复制两份无缝）。
- hover 暂停（便于点选）；不可达 skill 灰显✗。

### 4.3 Plan/提示合一（不显全 Plan）
- `.plan-tip` = 小圆点（4，done=lake/cur=sun/todo=灰）+ 文本行。
- 文本：**需提示时显 tip**（"💡 调整站位至目标区"）；**完成某项时显"✓ <环节>已完成"**（如"✓ 机位已完成"）。
- **不显全 Plan**（Plan 给 Agent 自看；用户只关心进度/做到哪）。小圆点同步变色。体现"Agent 时刻在身边"。
- 推进：侧边"Eval推进→"→当前步完成→显"✓X已完成"~1.9s→小圆点推进→回显下一步 tip。

### 4.4 overlay（preview 中部，无顶部 text）
- rule_of_thirds + bbox（**左侧小** normalized [0.10,0.28,0.30,0.44]）+ arrow（指向目标区）+ 锚点 + reference_overlay/PIP（**右侧**）。
- **无 `.txt` top 层**（提示只在 hud-band）。小人初始 figX=0.62（中间靠右）；分身入画时叠加半透明分身像。

---

## 5. 技术结论（系统相机不可嵌入）

不能嵌入原生 iOS"相机"App UI（无公开 API；`UIImagePickerController(.camera)` 模态、不可定制、不允许 overlay）。唯一路径：`expo-camera`（[01-MVP §9.2](../01-MVP期-方案设计及计划.md)）自建全屏取景，复刻 iOS 相机主要功能（预览/`takePictureAsync`/`cameraType`/`flashMode`/`zoom` .5/1x/2/4/8），并可画 overlay + 机器人 HUD。> 变焦 .5/2/4 依赖设备多摄，Phase A 核实。

---

## 6. 端侧 VLM 架构注（P5 能力前移）

端侧 VLM(MiniCPM) 扫描/候选 + 持续 Eval + 择机抓拍 + 中途提醒 = [01-MVP §5 Phase 5](../01-MVP期-方案设计及计划.md) 端侧能力**前移到默认 UX**。Demo mock；开发期云端 [Qwen3-VL :8000 describe_scene](../../services/gateway) 兜底；真功能需端侧 MiniCPM。⚠️ 落地前评估端侧可行性/性能/发热，并在 [01-MVP §9.2](../01-MVP期-方案设计及计划.md) 增补"端侧 VLM 候选/Eval"前置项。

---

## 7. Skill 白名单（可实现性，扩展点）

人像类：拍女朋友/拍孩子/分身入画…；场景类：拍风景/拍古典建筑/拍美食/拍月亮…。Agent 扫描判当前场景能/不能（对天空拍飞机→分身入画/拍美食不可达；拍孩子→"拍孩子"置顶）。可达 skill 按相关度排序弹气泡。

---

## 8. Overlay 图层规格（不变）

`GuidanceLayer.kind`（[schemas/shooting.py](../../schemas/shooting.py) L78–95）：rule_of_thirds / bbox(`normalized=[x,y,w,h]`+`label`) / arrow / text / reference_overlay(alpha@0.35，⚠️ `opacity`/`previewId` 未在 schema，A.4 前瞻 PR2)。锚点为 mockup 视觉（小圆点），可后续加 `anchor` kind。

---

## 9. 数据绑定（字段名 = API camelCase 别名）

| 环节 | 请求 | 响应 |
|---|---|---|
| 扫描/候选 | 端侧 VLM 读预览 + skill 白名单 | 候选 + 可达性（mock）；开发期 `describe_scene` 兜底 |
| 点 skill/语音 | `POST /api/v1/sessions/{id}/submit-intent`（multipart `frame`+`userIntent=<skill 或 语音转文字>`） | `IntentPhaseResult{draftGoal,questions(默认空→跳过 confirm),conflicts,sceneFacts,aestheticDraft}` |
| 分身入画 skill | 前置 clone_id（mock）→ 后置帧 submit | 同上（scenario=`dual-cam-clone`） |
| Reference 轮询 | `GET .../reference-preview` → `GET .../reference-preview.png` | `ReferencePreviewPayload{status,dataRef,width,height,latencyMs,generator}` |
| Plan/Eval | `POST .../analyze-frame?phase=coarse_act\|fine_act` | `AnalyzeFrameResponse{compositionScore,vlmAlignScore,planDeviation,progressScore,guidanceOverlay,captureReady,captureReason,stepCompleted?}`（⚠️ PR2 待建；A.4 为契约；`stepCompleted` 前瞻） |

---

## 10. iOS 惯用 UI 约定

相机即主界面（`expo-camera` 全屏取景 + iOS chrome）；✦ 右上开关；机器人常驻呼吸、双击换边、短按/长按；气泡水平轮动；plan/tip 合一 + 小圆点；进度环/条、倒计时、横幅/模态（severe/plan_refresh/end_remind）；模拟控件外置侧边。

---

## 11. ⚠️ Schema 缺口

`AnalyzeFrameResponse`（含 `stepCompleted?`）未在 [schemas/shooting.py](../../schemas/shooting.py)（PR2 待建，A.4 为契约）；`GuidanceLayer.opacity`/`previewId` 未在 schema（A.4 前瞻，PR2 补）；`stepCompleted` 为 v3.0 新增前瞻字段。接真接口前须 PR2 落 schema，再校准 App `client.ts`。

---

## 12. 扩展性 / 可访问性

Skill 白名单 = 扩展点；全中文 UI；触控 ≥44pt；对比度 WCAG AA；severe/倒计时辅以文字；长按语音为可达性增强。

---

*文档结束。v3.1（2026-08-07）：HUD 收拢变焦上方带 + 双击切换 + 气泡水平轮动 + Plan/提示合一（去全 Plan）+ 模拟控件外置 + bbox 左小/小人居中靠右 + 去顶部 text。配套 [ios_app_ux_v3.html](ios_app_ux_v3.html)；旧 v2/v1/v0 被取代。*
