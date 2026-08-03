# Camera Agent Harness

This repository contains the WSL-hosted reasoning harness for HelloCamera. The
iPhone remains a camera and renderer; the harness owns the coaching task,
fixed plan, change gating, model calls, and protocol-v1 results.

The implementation is end-to-end:

- Strict WebSocket protocol-v1 validation and binary correlation
- Change-driven analysis that suppresses unchanged preview frames
- One stable plan with adaptive guidance per intention
- Gemini structured vision/reasoning
- On-demand transient still requests
- Asynchronous ComfyUI image editing for explicit visual-reference requests
- Text, overlay, readiness, and sample-image results
- Deterministic fakes, replay support, and live adapter smoke tests

The maintained design reference is
[docs/HARNESS_ARCHITECTURE.md](docs/HARNESS_ARCHITECTURE.md).

## Start the harness

The current Python environment already contains the required packages. To
create a separate environment:

```bash
cd /home/liujinyuan/Developer/agent_harness
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Export the Gemini key and ensure the existing editing endpoint is listening at
`http://127.0.0.1:8000/edit`:

```bash
export GEMINI_API_KEY='your-key'
python -m camera_agent
```

The WSL listener is:

```text
ws://0.0.0.0:8765/camera
```

On the verified Windows Mobile Hotspot setup, connect the iPhone to:

```text
ws://192.168.137.1:8766/camera
```

Windows forwards hotspot port `8766` to WSL port `8765`. Do not change the
existing port-proxy rule to use the same port on both sides. See
[docs/IPHONE_WSL_CONNECTION_GUIDE.md](docs/IPHONE_WSL_CONNECTION_GUIDE.md).

Useful options:

```bash
python -m camera_agent --help
python -m camera_agent --log-level DEBUG
python -m camera_agent --debug-artifacts ./debug-artifacts
python -m camera_agent --model gemini-3.5-flash-lite
```

All change thresholds are CLI-adjustable. For example:

```bash
python -m camera_agent \
  --zoom-relative-delta 0.02 \
  --attitude-delta-degrees 3
```

Higher change thresholds reduce VLM calls but may miss subtle movements.
Defaults, units, and tuning directions are in the
[architecture tuning table](docs/HARNESS_ARCHITECTURE.md#change-detection).

The harness assumes ComfyUI is already running. It never starts, stops, or
supervises that process.

## Ask for a generated visual reference

Image generation requires explicit wording in the shooting intention, for
example:

```text
A confident full-body portrait. Show me a reference pose.
```

The harness may then request a transient 1024 px still, edit it, and send the
result back as an explicitly labeled AI-generated reference. Ordinary pose
advice does not authorize editing.

## Tests

Run deterministic tests:

```bash
pytest -q
```

These tests use fake model adapters and include real loopback WebSocket
round trips. They do not call Gemini or ComfyUI.

Run the opt-in production adapter smoke tests:

```bash
RUN_LIVE_AGENT_TESTS=1 pytest tests/test_live_integration.py -q -s
```

This makes one real Gemini request and one real editing request.

Run static checks:

```bash
ruff check camera_agent tests
python -m compileall -q camera_agent tests
```

## Replay

Replay a JSONL manifest through Gemini without opening a WebSocket:

```bash
python -m camera_agent --replay path/to/replay.jsonl
```

Each non-comment line contains a strict protocol-v1 observation and an image
path relative to the manifest:

```json
{"observation":{"type":"observation","version":1,"messageId":"11111111-1111-4111-8111-111111111111","observationId":1,"timestampMs":1000,"reason":"intention_updated","intention":"A confident portrait","camera":{"lensID":"wide-camera","lensName":"Back Camera","zoomFactor":1,"focalLength35mm":24,"focusPoint":null,"exposurePoint":null,"exposureBias":0,"iso":50,"exposureDurationSeconds":0.01,"whiteBalanceRedGain":2,"whiteBalanceGreenGain":1,"whiteBalanceBlueGain":1.8,"flashMode":"off","orientation":"portrait","frameWidth":480,"frameHeight":640,"cropAspectRatio":0.75,"rollRadians":0,"pitchRadians":0},"imageMessageId":"22222222-2222-4222-8222-222222222222"},"imagePath":"frame-0001.jpg"}
```

## Security

This is a trusted-LAN development harness. `ws://` sends images, intentions,
and metadata without encryption or authentication. Keep the Windows firewall
rule restricted to the private hotspot subnet. Add TLS, pairing,
authentication, and retention controls before distribution.
