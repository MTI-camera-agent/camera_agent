# P2 Gateway 访问说明（WSL2 / 局域网 / Tunnel）

Gateway 同源托管 H5 与 API：`services.gateway.main:app`，默认绑定 `0.0.0.0:8787`。

## 启动

```bash
# 仓库根目录；需已配置 shooting.main_agent / qwen3vl（与 P1 相同）
uvicorn services.gateway.main:app --host 0.0.0.0 --port 8787
```

可选环境变量：`CAMERAAGENT_CONFIG=/path/to/config.yaml`。

配置节见 `config.yaml` → `gateway:`（`demo_token`、`max_frame_long_edge`、帧/计划落盘目录等）。

| 入口 | URL |
|------|-----|
| H5 | `http://<host>:8787/` |
| 设计稿 Mock | `http://<host>:8787/?mock=1` |
| Health | `http://<host>:8787/healthz` |
| OpenAPI | `http://<host>:8787/docs` |

鉴权：若 `gateway.demo_token` 非空，请求头需带 `X-Demo-Token`；H5 可用 `?token=` 写入并缓存到 `localStorage`。

## 访问场景

| 场景 | 做法 |
|------|------|
| 本机 PC 浏览器 | `http://127.0.0.1:8787` |
| 同 WiFi 手机 | 使用 **Windows 主机局域网 IP**:`8787`。WSL2 推荐 **mirrored networking**，或 `netsh interface portproxy` 把 Windows `8787` 转到 WSL IP；Windows 防火墙入站放行 8787 |
| 公网 / 外网演示 | **Cloudflare Tunnel**（或同类）指向 `http://127.0.0.1:8787`，对外给出 `https://…` |
| 相机「拍照」 | 需要 **Secure Context**：公网必须 HTTPS（Tunnel）。纯局域网 HTTP 下优先 **相册上传**；在 HTTPS 下再验证 `capture="environment"` |

P2 **不做** WebRTC / 持续实时预览流。

### WSL2 portproxy 示例（Windows 管理员 PowerShell）

```powershell
# 将 WSL 的 eth0 IP 替换为实际地址（wsl hostname -I）
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8787 `
  connectaddress=<WSL_IP> connectport=8787
# 防火墙放行（一次性）
New-NetFirewallRule -DisplayName "CameraAgent 8787" -Direction Inbound -LocalPort 8787 -Protocol TCP -Action Allow
```

Mirrored networking（Windows 11）：在 `.wslconfig` 中设置 `networkingMode=mirrored` 后，手机可直接访问 Windows 主机 IP 的 `8787`（仍需防火墙放行）。

### Cloudflare Tunnel 示意

```bash
# 本机已登录 cloudflared 的前提下
cloudflared tunnel --url http://127.0.0.1:8787
# 使用输出的 https://*.trycloudflare.com 在手机上打开
```

## API 摘要（与 M1 契约一致）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/sessions` | 创建内存 Session |
| POST | `/api/v1/sessions/{id}/submit-intent` | multipart：`frame` + `userIntent` → Question |
| POST | `/api/v1/sessions/{id}/confirm-intent` | JSON `answers` → Plan；`referencePreview.status=generating`（P3 真出图） |
| GET | `/api/v1/sessions/{id}` | 查状态 / 最近结果 |

帧：JPEG/PNG，服务端长边 ≤ `max_frame_long_edge`（默认 1280）。

## 验收（M2）

```bash
uvicorn services.gateway.main:app --host 0.0.0.0 --port 8787
# PC: http://127.0.0.1:8787  手机局域网或 Tunnel HTTPS
# 图库或拍照 → 意图 → Question → Plan；字段与 P1 shooting_plan 一致
pytest -q
```
