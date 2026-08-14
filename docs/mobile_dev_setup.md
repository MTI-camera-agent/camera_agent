# iOS App（Expo / React Native）Demo 开发运行手册

- **版本**：v1.0（2026-08-04）
- **状态**：Active — 环境就绪；App 未编码（Phase A–E 为 TODO）
- **依据**：[01-MVP期-方案设计及计划.md](01-MVP期-方案设计及计划.md) §12 App-Demo、[p3_act_channels.md](p3_act_channels.md)、[p2_gateway_access.md](p2_gateway_access.md)

> 本文是 **CameraAgent iOS 端 Demo** 的开发/运行手册：在 **WSL2（无本地 Mac）** 下用 **Expo + Expo Go** 配合 **iPhone 真机** 调试端云功能。**Demo 阶段推理仍在云端**；端侧下沉属 P5（未来）。

---

## 0. 前提纠正

- **Flutter iOS 即使 Demo 也绕不开 Mac**：`xcodebuild`/签名/模拟器均仅 macOS，WSL2 无 iOS 工具链。"Mac 仅发布时需要"**不适用于 Flutter iOS**。
- **Expo + Expo Go** 是唯一匹配"WSL2 开发 + iPhone 真机测 + Demo 阶段零 Mac、仅发布时云端 Mac"的方案。已决议为 P5 技术栈（O4 → React Native (Expo)）。

---

## 1. 环境就绪（已完成）

| 项 | 状态 |
|---|---|
| Node.js v22.22.0 | ✅ |
| Expo CLI 57.0.11（`npx expo --version`） | ✅ |
| watchman | ✅ |
| iPhone "Expo Go"（已登录 expo.dev） | ✅ |

> 若环境缺失：`nvm install 20`、`sudo apt install -y watchman`、App Store 装 "Expo Go"、`npx expo login`。

---

## 2. 端到端通路

```
iPhone(Expo Go, 跑 TS bundle)
   │ ① 加载 bundle ─► Expo dev server(WSL2 :8081)  ← npx expo start --tunnel（公网 HTTPS，Expo 自动提供）
   │ ② 业务 fetch  ─► cloudflared tunnel ─► FastAPI 网关(WSL2 127.0.0.1:8787)
   └─ App 只打 :8787；:8000/8001/8188/8010 是网关内部推理后端，App 不直接访问
```
两条通道（①加载 bundle、②业务请求）均走 HTTPS 隧道，**绕开 WSL2 的 NAT**，无需 `netsh portproxy`（LAN 方案见 §6 Plan B）。

---

## 3. 运行手册（TODO 步骤，未执行）

### 3.1 后端侧（一次性）
- [ ] `config.yaml` 第 80 行 `gateway.cors_origins: []` → `["*"]`（Expo Go 跨源 fetch 需放开）。
- [ ] 启网关：`uvicorn services.gateway.main:app --host 0.0.0.0 --port 8787`（详见 [p2_gateway_access.md](p2_gateway_access.md)）。
- [ ] 启隧道：`cloudflared tunnel --url http://127.0.0.1:8787` → 拿到 `https://<x>.trycloudflare.com`。
- [ ] （可选）`gateway.demo_token` 设非空则在 App 侧带 `X-Demo-Token`。

### 3.2 App 侧
- [ ] 脚手架：`npx create-expo-app@latest mobile --template blank-typescript`（放仓库内 `mobile/`）。
- [ ] 装模块：`cd mobile && npx expo install expo-image-picker expo-camera expo-secure-store react-native-safe-area-context`。
- [ ] `mobile/.env`：
  ```
  EXPO_PUBLIC_API_BASE=https://<x>.trycloudflare.com
  EXPO_PUBLIC_DEMO_TOKEN=
  ```
- [ ] `src/api/client.ts` 逐段移植 [../frontend/web/app.js](../frontend/web/app.js)：
  - `const API_BASE = process.env.EXPO_PUBLIC_API_BASE + "/api/v1"`
  - 可选 `X-Demo-Token` 头（镜像 app.js §headers）
  - `POST /sessions` → `POST .../submit-intent`（FormData 严格字段名 `frame` + `userIntent`）→ `POST .../confirm-intent`（JSON `{answers:[{questionId,value}]}`）→ 轮询 `GET .../reference-preview`（1500ms）→ `GET .../reference-preview.png`
  - TS 类型照 [../schemas/shooting.py](../schemas/shooting.py)（camelCase 别名已落地）
- [ ] `src/screens/` 移植 S0(相册选帧, `expo-image-picker`)/S1(问询 chips)/S2(方案步骤+参考图 PIP)。本阶段 S0 只用相册。
- [ ] 起 Expo：`npx expo start --tunnel` → 控制台出二维码 → iPhone Expo Go 扫码。

---

## 4. WSL2 → iPhone 网络可达性

**主方案（推荐，零网络配置）**
- Expo dev server：`npx expo start --tunnel`——Expo 自动给 dev server 配公网 HTTPS URL，Expo Go 扫码即连，绕过 WSL2 NAT。提示装隧道包则同意。
- 业务请求：走 §3.1 的 `cloudflared` 隧道 HTTPS URL。

**Plan B（纯局域，断网/低延迟调试）**
- WSL2 mirrored networking（Win11 22H2+，`%UserProfile%\.wslconfig` 设 `networkingMode=mirrored`）后 iPhone 可直连 Windows LAN IP。
- 或经典端口转发（PowerShell 管理员，复用 [p2_gateway_access.md](p2_gateway_access.md) 模式）：
  ```powershell
  netsh interface portproxy add v4tov4 listenport=8081 listenaddress=0.0.0.0 connectport=8081 connectaddress=<WSL2_IP>
  netsh interface portproxy add v4tov4 listenport=8787 listenaddress=0.0.0.0 connectport=8787 connectaddress=<WSL2_IP>
  ```
  然后 `npx expo start`（不带 `--tunnel`）走 LAN；App 的 `EXPO_PUBLIC_API_BASE=http://<Win_LAN_IP>:8787`。**注意**：Expo Go 在 iOS 上对纯 HTTP 后端可能受 ATS 限制，仍优先用隧道 HTTPS。

---

## 5. 相机权限与 iOS ATS

- **相机权限**：`app.json` 必加 `expo-camera` plugin + `ios.infoPlist.NSCameraUsageDescription`，否则 Phase B 取景崩。
- **iOS ATS**：Expo Go 对纯 HTTP 后端可能受限；一律走 `cloudflared` HTTPS（相机 API 同样需 HTTPS 安全上下文，与 H5 一致）。

---

## 6. 后续编码 TODO（Phase A–E，未执行）

> 两条 Track 并行。详见主文档 [§12](01-MVP期-方案设计及计划.md#12-app-demo-车辆与后续编码-todo2026-08-04-新增)。

| Track | 阶段 | 交付 | 命中 | 依赖 |
|---|---|---|---|---|
| App | A 骨架+端云打通 | App 重做 M2（相册选帧→问询→方案+参考图 PIP） | M2'(App parity) | 网关+隧道 |
| App | B 实时取景预览 | `expo-camera` 实时预览+抓拍→`submit-intent` | 解锁相机调试 | A |
| App | C P3 Channel B overlay | 取景层渲染 `GuidanceLayer`+2fps `analyze-frame`+severe 横幅 | M3 ①③④ | A、B、后端 PR2 |
| App | D P4 精调闭环+快门 | 2s `fine_act`+参考图 alpha+`capture_ready`+3s 倒计时 | M4 | C、后端 P4 |
| 后端 | PR1 reference_preview（已实现未实测） | 由 App A/C 的 PIP 真机实测 | M3 ② | 起 :8188 |
| 后端 | PR2 Channel B 粗调 loop | `analyze-frame?phase=coarse_act`+CV 四件套 | M3 ①③④ | PR1 |
| 后端 | P4 fine_act | MiniCPM coach + :8001 接拍照环 | M4 | PR2 |

### Phase A — App 骨架 + 端云打通（重做 M2 on App）
- [ ] 见 §3.1 + §3.2 全部步骤。
- **验收（M2'）**：相册选 `test_img/01-input_frame.png` + 意图 → 问询 → 方案 + 参考图 PNG（≤30s）。兼完成 PR1 真机实测（M3 ②）。

### Phase B — 实时取景预览 + 抓拍
- [ ] `app.json` 加 `expo-camera` plugin + `NSCameraUsageDescription`（见 §5）。
- [ ] S0 增取景入口：`expo-camera` 实时预览 + 抓拍 → `submit-intent`（复用 `client.ts`）。
- **验收**：实时预览 + 抓拍走通 P2。

### Phase C — P3 Channel B 引导叠加（App + 后端 PR2，M3 ①③④）
- **App**：取景层上方透明 canvas 按 `coarseGuidance.layers`（`GuidanceLayer`：rule_of_thirds/bbox/text/arrow/reference_overlay，见 [../schemas/shooting.py](../schemas/shooting.py)）渲染；静态先行（confirm-intent 返回值）；动态 ~2fps 抓帧 → `POST /api/v1/sessions/{id}/analyze-frame?phase=coarse_act` → 画 `guidanceOverlay` + `compositionScore` + `planDeviation`；severe 弹退出横幅。
- **后端 PR2**（文件级见 [p3_act_channels.md](p3_act_channels.md) §4）：[../schemas/shooting.py](../schemas/shooting.py) 补 `CompositionScore`/`AnalyzeFrameRequest/Response`/`progressScore`/`captureReady`；[../requirements.txt](../requirements.txt) 加 `opencv-python`+`numpy`；skills `cv_guide`/`composition_score`/`overlay_compose`/`plan_deviation`；[../workflow/shooting_loop.py](../workflow/shooting_loop.py) 加 `analyze_frame(phase=coarse_act)`；[../services/gateway/routes/sessions.py](../services/gateway/routes/sessions.py) 加 `POST /sessions/{id}/analyze-frame`（fine_act 501）。
- **验收（M3 ①③④）**：confirm 后 overlay 同步；analyze-frame 返回 score/deviation；5 帧<0.35 触发 severe。

### Phase D — P4 精调闭环 + 快门（App + 后端 P4，M4）
- **App**：~2s 送帧 `analyze-frame?phase=fine_act`；参考图 alpha 叠加（opacity≈0.35）+ 对齐进度条（`progressScore=0.4*composition+0.6*vlm_align`）；`captureReady=true` → 绿色就绪 + 3s 倒计时；severe → 退出。
- **后端 P4**：`agents/coach.py`（MiniCPM 精调）；`models/minicpm_vision.py` + `factory.py` 注册；[../workflow/shooting_loop.py](../workflow/shooting_loop.py) `fine_act`；MiniCPM `:8001` 接拍照环（送帧间隔 2s，O3）。
- **验收（M4）**：正例达 `capture_ready`；负例 severe；2s P95<3s；`progressScore` 文案一致。

### Phase E — P5 端侧下沉（未来，Demo 之外）
- 端侧 MiniCPM-V-4.6 + 离线 Act；届时用 §7 的 `eas build`。

---

## 7. 发布阶段（Mac 仅此时，云端）

```bash
cd mobile && npm i -g eas-cli && eas login
eas build --platform ios --profile preview   # 云端 macOS worker 构建+签名
eas submit -p ios                             # TestFlight / App Store
```
此即"仅发布时需要 Mac"——由 Expo EAS 的云端 macOS 完成，本地仍无需 Mac。

---

## 8. 注意点

- **iOS ATS**：一律走隧道 HTTPS（纯 HTTP 后端可能被 ATS 拦，相机 API 同样需 HTTPS）。
- **相机权限**：`app.json` 必配 `NSCameraUsageDescription`，否则 Phase B 崩。
- **Phase C/D 依赖后端 PR2/P4**：App 单独跑不了 `analyze-frame`/`fine_act`，需后端 Track 并行；建议 A/B 先行（无新后端依赖），C/D 与后端 PR2/P4 同步。
- **Demo 不做端侧推理**：Act 仍走云端；端侧 MiniCPM 属 P5。
- **`mobile/` 与 `frontend/web/` 并存**：H5 不动，App 是新前端；两者打同一套 `/api/v1`，便于对照调试。

---

*文档结束。v1.0（2026-08-04）：初版，配套主文档 §12 App-Demo。后续随 Phase 推进更新勾选。*
