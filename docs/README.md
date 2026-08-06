# HelloCamera

HelloCamera is a portrait-only iOS 26 camera client for a desktop camera agent.
The phone owns camera interaction and presentation. The desktop owns agent
state, planning, memory, models, and tools.

## What is implemented

- 4:3 rear-camera preview with pure-black control regions
- Continuous pinch zoom over the device-supported range, capped at 0.5×–25×
- Tap focus/exposure with capture-time focus settling
- Interactive exposure-bias control
- Full-quality user captures saved to Photos
- Explicit shooting-intention updates
- Approximately 2 FPS JPEG observations, maximum long edge 640 px
- User and agent-requested network stills, maximum long edge 1024 px
- Camera, exposure, crop, and optional roll/pitch metadata
- WebSocket reconnect without offline buffering
- Agent text, normalized overlays, and expandable sample images
- Strict protocol-v1 validation and a machine-readable JSON Schema
- A validated Python mock desktop agent

The app has no aperture/F-stop simulation, video recording, front-camera mode,
flash control, RAW capture, manual ISO/shutter controls, discovery, or pairing.

## Build and use without a desktop

The server is optional. Open `HelloCamera.xcodeproj`, choose your development
team and an iPhone running iOS 26 or newer, then Run. Grant Camera, Motion, Local
Network, and Add Photos permissions when requested.

Preview, zoom, focus, exposure, shutter, intention editing, and local photo
saving work while the app is offline. Agent guidance simply remains inactive.
An unavailable endpoint does not stop the camera; the app retries in the
background.

## Run the mock agent in WSL

From the repository:

```bash
python3 -m venv mock_server/.venv
source mock_server/.venv/bin/activate
python3 -m pip install -r mock_server/requirements.txt
python3 mock_server/mock_camera_agent.py
```

The server binds `0.0.0.0:8765` and serves `/camera`.

### Same Wi-Fi

Use the Windows PC's Wi-Fi IPv4 address in the app:

```text
ws://<windows-wifi-ip>:8765/camera
```

Guest networks may block communication between devices.

### Windows mobile hotspot

1. Enable Mobile hotspot and connect the iPhone.
2. Find the hotspot adapter's IPv4 address with `ipconfig`. It is often
   `192.168.137.1`.
3. Allow inbound TCP port 8765 in Administrator PowerShell:

```powershell
New-NetFirewallRule -DisplayName "HelloCamera mock agent" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765
```

4. With WSL mirrored networking, direct access may use
   `ws://<windows-hotspot-ip>:8765/camera`. On this desktop, the Wi-Fi Direct
   hotspot adapter was not exposed directly and Windows already owned localhost
   port 8765, so the verified setup instead forwards Windows hotspot port 8766
   to WSL localhost port 8765. See
   [IPHONE_WSL_CONNECTION_GUIDE.md](IPHONE_WSL_CONNECTION_GUIDE.md).
5. With WSL NAT, get the current WSL address using `wsl hostname -I` and add a
   Windows port proxy:

```powershell
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8765 connectaddress=<WSL-IP> connectport=8765
```

The WSL NAT address may change after a restart.

This prototype permits plaintext `ws://` for trusted private networks. Add TLS,
authentication, and pairing before using it on an untrusted network.

## Physical-device acceptance checklist

- Preview is an unstretched 4:3 image; the regions above and below remain black.
- Pinch zoom is continuous and the top readout updates interactively.
- The actual minimum/maximum may be narrower on hardware without the required
  virtual-camera zoom range; the app never invents unavailable zoom.
- Tap focus shows a reticle, and the saved photo uses the requested focus point.
- Exposure bias updates interactively without moving the shutter controls.
- Stream observations arrive near 2 FPS and have a maximum 640 px long edge.
- Intention and camera events produce immediate event observations.
- Each overlay expires independently; zooming clears current overlays at once.
- Agent stills are transient and at most 1024 px; user captures also save the
  full-quality original to Photos.
- Disconnecting the server leaves camera controls usable; reconnect sends
  `hello` followed by a fresh observation.

## Tests

Run the Swift protocol/policy tests:

```bash
swift test
```

Install the pinned Python dependencies, then run schema, framing, and WebSocket
integration tests:

```bash
python3 -m venv mock_server/.venv
source mock_server/.venv/bin/activate
python3 -m pip install -r mock_server/requirements.txt
python3 -m unittest \
  mock_server.test_protocol \
  mock_server.test_schema \
  mock_server.test_integration
```

Build the iOS app without signing:

```bash
xcodebuild -project HelloCamera.xcodeproj \
  -scheme HelloCamera \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/HelloCameraDerived \
  CODE_SIGNING_ALLOWED=NO build
```

The concise v1 normative contract is [PROTOCOL.md](PROTOCOL.md). Desktop harness
development should begin with
[DESKTOP_AGENT_GUIDE.md](DESKTOP_AGENT_GUIDE.md). The executable v1 contract is
[protocol-v1.schema.json](protocol-v1.schema.json).

The implementation-ready v2 planning set is:

- [Camera Agent Harness v2 specification](CAMERA_AGENT_V2_SPEC.md)
- [maintained harness architecture](HARNESS_ARCHITECTURE.md)
- [protocol-v2 interaction extension](PROTOCOL_V2.md)
- [protocol-v2 extension schema](protocol-v2.schema.json)
- [v2 evaluation and release contract](CAMERA_AGENT_V2_EVALUATION.md)

Protocol v2 is not yet implemented by the current phone or harness.

The frozen protocol-v1 baseline and the per-behavior v2 delta classification
live in [V1_BASELINE_DELTAS.md](V1_BASELINE_DELTAS.md).
