# P2 UI — 三屏交互说明

手机优先的 H5 壳，路径 [`frontend/web/`](../frontend/web/)。视觉：冷墨青 + 湖色主按钮 + 浅雾底，Fraunces / IBM Plex Sans；非紫白渐变、非奶油衬线套件。

## 三屏

| 屏 | 内容 | 交互 |
|----|------|------|
| **S0 选帧** | 大预览区；「从相册选择」「拍照」；意图输入；「分析」 | `input[type=file]` 双路径；`capture="environment"` 为单次抓拍，非实时预览流。无帧时「分析」禁用。 |
| **S1 Question** | `draftGoal`；冲突摘要可折叠；1–2 题卡片 + option chips | 每题必选一项后「确认并生成方案」可点；可返回改图。 |
| **S2 Plan** | 步骤条 + `coarseGuidance.adviceText` + 只读 `editInstruction` | 「再拍一组」清空会话回到 S0。 |

## 空 / 错态

- 未选帧：预览区文案「还没有取景帧」。
- 非图片 / 分析失败 / 4xx：`status.error` 红字提示。
- 加载中：按钮文案旁状态行显示「分析中… / 生成方案中…」。

## Mock 与真 API

- 设计态：打开 `/?mock=1`，本地 JSON 驱动三屏，无需后端。
- 接线态：同域托管后去掉 `mock`；`POST /api/v1/sessions` → `submit-intent` → `confirm-intent`。
- 可选鉴权：`?token=` 或 `localStorage.cameraagent_demo_token` → 请求头 `X-Demo-Token`。

## 相机与安全上下文

局域网纯 HTTP 下优先用相册上传；`getUserMedia` / 部分手机相机入口需要 **Secure Context**（HTTPS）。外网演示用 Cloudflare Tunnel 等给出 `https://` 后再验「拍照」路径。
