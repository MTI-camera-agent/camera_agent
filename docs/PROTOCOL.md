# HelloCamera WebSocket protocol v1

This file is the concise protocol contract. The normative field definitions are
in [protocol-v1.schema.json](protocol-v1.schema.json), using JSON Schema Draft
2020-12. The desktop implementation guide is
[DESKTOP_AGENT_GUIDE.md](DESKTOP_AGENT_GUIDE.md).

## Transport

- WebSocket endpoint: `/camera`
- JSON messages: UTF-8 text frames
- Images: binary frames containing:

```text
4-byte unsigned big-endian JSON-header length
JSON header bytes
raw JPEG or PNG bytes
```

Do not base64-encode images. The reference server caps a complete WebSocket
message at 8 MiB.

All known v1 messages are closed objects: required fields, types, UUID formats,
and allowed values must match the schema, and unknown fields are rejected.
Optional properties may be absent; `null` is accepted only where the schema
explicitly permits it. Unknown text-message types may be ignored for forward
compatibility.

## Identity, IDs, and ordering

- The client completes `hello` transmission before sending any observation on a
  new connection.
- For each observation/image pair, its `observation` text is sent before its
  `preview_image` binary.
- Different pairs may interleave. Never depend on adjacency.
- A `result` must precede its referenced `result_image`.
- Correlate using `imageMessageId`, `messageId`, `observationId`, and
  `requestId`, not timing.
- UUID fields contain RFC 4122 UUID strings.
- `observationId` increases for one app process, survives socket reconnects, and
  may reset after app restart.
- `timestampMs` is Unix epoch milliseconds for diagnostics. Phone and desktop
  clocks are not assumed synchronized.
- Messages are not buffered for replay while disconnected.

## Client to desktop

| Type | Purpose |
| --- | --- |
| `hello` | Client identity/capabilities; first message on every connection |
| `observation` | Intention, reason, camera settings, and preview correlation |
| `preview_image` | Oriented 4:3 JPEG, approximately 2 FPS, maximum long edge 640 px |
| `high_resolution_image` | JPEG still, maximum long edge 1024 px |
| `error` | `busy`, `rate_limited`, or `invalid_message` |

Observation reasons are `stream`, `reconnected`, `intention_updated`,
`zoom_changed`, `focus_changed`, `exposure_changed`, and `user_capture`.

`high_resolution_image.initiation` is `agent` or `user`. Agent captures carry
the request UUID and are transient. User captures omit/null `requestId`; their
full-quality originals are saved locally.

## Desktop to client

| Type | Purpose |
| --- | --- |
| `result` | Guidance text, overlays, and/or a sample-image reference |
| `result_image` | JPEG/PNG sample image referenced by a result |
| `capture_high_resolution` | Request a transient 1024 px still |

A `result` requires `version`, UUID `messageId`, positive `observationId`,
nonnegative `timestampMs`, and at least one of nonempty `text`, nonempty
`overlays`, or UUID `imageMessageId`.

Overlay kinds are `arrow`, `line`, `rectangle`, `circle`, `path`, and `text`.
Coordinates are normalized to the exact transmitted preview: `(0,0)` is
top-left and `(1,1)` is bottom-right. Arrow/line/path require at least two
points; rectangle/circle exactly two; text exactly one and nonempty `text`.
Colors use `#RRGGBB`; widths and expiry durations are positive.

If any field or overlay in a known incoming message is invalid, the client
rejects the whole message, retains previously rendered valid guidance, shows a
transient error, and sends an `error` with code `invalid_message`.

## Freshness and rendering

- Results older than the latest accepted result observation are ignored.
- Results whose observation context has fallen outside the client's retained
  recent window are ignored.
- Text changes only when a valid accepted result contains `text`.
- Omitting `overlays` clears overlays for that accepted result.
- The last successfully decoded sample image remains visible; a new result
  cancels any pending unmatched image reference.
- Spatial overlays render only when their source observation is at most two
  seconds old and lens, zoom, orientation, dimensions, and crop still match.
- Zoom changes clear overlays immediately.
- Each overlay expires independently using `expiresInMilliseconds`.
