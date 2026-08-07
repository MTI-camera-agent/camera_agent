"""Private deterministic frame-signal measurement for the v2 runtime.

This module is **not** a public semantic seam and is **not** exported from
``camera_agent.v2``. It realizes the CPU-cheap deterministic frame measurements
(spec §4.2) the runtime reducer owns as an internal responsibility:
compatible camera-context metadata deltas, thumbnail / global / local difference
and hash-supported change signals, mutual equivalence of post-change frames,
relative sharpness/blur regression, and luminance and highlight/shadow clipping
measurements.

The reducer owns the *policy* (material-change assessment, asymmetric Settled
hysteresis, invalidation, coalescing). This module owns only the *measurement*:
it turns two ``Observation`` values into one ``FrameSignals`` value. Production
decodes previews with Pillow; deterministic tests substitute a scripted callable
through ``build_runtime(signal_computer=...)`` — a private mechanical
substitution, not a fakeable public Adapter seam (spec §“Rejected architecture
shapes”: do not wrap deterministic policies in fakeable public Interfaces only
to enable narrow unit tests).

Deterministic signals MAY invalidate Evidence, influence Settled, request
reasoning, or enter a Context Pack. They MUST NOT establish semantic achievement,
subject presence, framing correctness, or Readiness.
"""

from __future__ import annotations

import math
from io import BytesIO

from .config import FrameSignalPolicy
from .values import FrameSignals, Observation


class PILFrameSignalComputer:
    """Production deterministic frame-signal measurement over preview bytes.

    Decodes each preview to a small grayscale thumbnail and computes:

    - a hard camera-context change (lens / orientation / frame dimensions);
    - a translation-tolerant global/block mean-absolute-error and d-hash
      distance against the reference observation (the material visual delta);
    - relative sharpness (1 - normalized high-frequency energy) and a blur
      regression crossing against the reference;
    - mean luminance and highlight/shadow clipping fractions; and
    - mutual equivalence (a routine frame coalesces without a new identity).

    Decode failure yields unavailable quality data and conservative fail-open
    change handling (``material_change=True``). A relative sharpness/luminance/
    clipping crossing is reported via ``quality_crossing`` and requests
    revalidation only; it is never itself a material invalidation (S04). All
    numeric measurements are normalized to ``[0, 1]`` and are diagnostic only;
    they never establish Ready.
    """

    def __init__(self, policy: FrameSignalPolicy) -> None:
        self._policy = policy

    def compute(self, reference: Observation | None, candidate: Observation) -> FrameSignals:
        hard_reasons = self._hard_camera_reasons(reference, candidate)
        try:
            cand_thumb, cand_hash = self._signature(candidate)
        except Exception:
            # Decode failure: unavailable quality data, conservative fail-open.
            return FrameSignals(
                decode_available=False,
                material_change=True,
                equivalent_to_reference=False,
                material_reasons=tuple(hard_reasons) + ("decode_unavailable",),
            )

        if reference is None:
            # First post-change frame: no reference to compare against. It is
            # the baseline of a new settling period, not an invalidation.
            return FrameSignals(
                decode_available=True,
                material_change=False,
                equivalent_to_reference=False,
                relative_sharpness=self._sharpness(cand_thumb),
                luminance=self._luminance(cand_thumb),
                highlight_clipping=self._clipping(cand_thumb, high=True),
                shadow_clipping=self._clipping(cand_thumb, high=False),
            )

        try:
            ref_thumb, ref_hash = self._signature(reference)
        except Exception:
            # The reference cannot be decoded: treat the candidate as a fresh
            # baseline (no comparable reference). Quality data stays available.
            return FrameSignals(
                decode_available=True,
                material_change=False,
                equivalent_to_reference=False,
                relative_sharpness=self._sharpness(cand_thumb),
                luminance=self._luminance(cand_thumb),
                highlight_clipping=self._clipping(cand_thumb, high=True),
                shadow_clipping=self._clipping(cand_thumb, high=False),
            )

        global_mae, block_mae = self._translation_tolerant_mae(ref_thumb, cand_thumb)
        hash_distance = sum(a != b for a, b in zip(ref_hash, cand_hash, strict=True))
        reasons = list(hard_reasons)
        if global_mae >= self._policy.visual_material_global_mae:
            reasons.append("visual_global")
        if block_mae >= self._policy.visual_material_block_mae:
            reasons.append("visual_local")
        hash_support = (
            global_mae >= self._policy.visual_material_global_mae / 2
            or block_mae >= self._policy.visual_material_block_mae / 2
        )
        if (
            hash_distance >= self._policy.visual_material_hash_distance
            and hash_support
        ):
            reasons.append("visual_hash")

        sharpness = self._sharpness(cand_thumb)
        ref_sharpness = self._sharpness(ref_thumb)
        luminance = self._luminance(cand_thumb)
        ref_luminance = self._luminance(ref_thumb)
        highlight = self._clipping(cand_thumb, high=True)
        shadow = self._clipping(cand_thumb, high=False)

        sharpness_regression = (
            ref_sharpness is not None
            and sharpness is not None
            and (ref_sharpness - sharpness) >= self._policy.sharpness_regression_threshold
        )
        luminance_delta = (
            abs(luminance - ref_luminance)
            if luminance is not None and ref_luminance is not None
            else 0.0
        )
        quality_crossing = (
            sharpness_regression
            or luminance_delta >= self._policy.luminance_change_threshold
            or (highlight is not None and highlight >= self._policy.highlight_clipping_threshold)
            or (shadow is not None and shadow >= self._policy.shadow_clipping_threshold)
        )
        # A calibrated quality crossing (relative blur / luminance / clipping
        # regression) may request revalidation only; it MUST NOT itself be a
        # material invalidation (S04). Material-ness is driven solely by hard
        # camera-context change and material visual global/local/hash deltas,
        # so a quality crossing never enters ``material_reasons``. A frame may
        # be both equivalent (no material visual delta) and quality-crossing;
        # the runtime then marks guidance as needing revalidation rather than
        # invalidating the Evidence identity.
        material = bool(reasons)
        # Equivalence: a routine frame well within the material thresholds and
        # with no quality crossing coalesces without a new Evidence identity.
        equivalent = (
            not material
            and global_mae < self._policy.visual_material_global_mae
            and block_mae < self._policy.visual_material_block_mae
        )
        return FrameSignals(
            decode_available=True,
            material_change=material,
            equivalent_to_reference=equivalent,
            material_reasons=tuple(reasons),
            relative_sharpness=sharpness,
            luminance=luminance,
            highlight_clipping=highlight,
            shadow_clipping=shadow,
            sharpness_regression=sharpness_regression,
            quality_crossing=quality_crossing,
        )

    # --- camera-context hard change -------------------------------------

    def _hard_camera_reasons(
        self, reference: Observation | None, candidate: Observation,
    ) -> list[str]:
        if reference is None:
            return []
        reasons: list[str] = []
        ref = reference.camera.metadata
        cand = candidate.camera.metadata
        for key in self._policy.camera_hard_change_keys:
            if ref.get(key) != cand.get(key):
                reasons.append(f"camera:{key}")
        return reasons

    # --- thumbnail + d-hash signatures ----------------------------------

    def _signature(self, observation: Observation) -> tuple[list[float], tuple[bool, ...]]:
        size = self._policy.visual_thumbnail_size
        with _open_image(observation) as image:
            grayscale = image.convert("L")
            thumb = grayscale.resize((size, size)).filter(
                _gaussian_blur(self._policy.visual_blur_radius)
            )
            hash_image = grayscale.resize((9, 8))
        return self._mean_centered(thumb), self._difference_hash(hash_image)

    @staticmethod
    def _mean_centered(image) -> list[float]:  # type: ignore[no-untyped-def]
        from PIL import ImageStat

        values = list(image.tobytes())
        mean = ImageStat.Stat(image).mean[0]
        return [max(0.0, min(255.0, v - mean + 128.0)) for v in values]

    @staticmethod
    def _difference_hash(image) -> tuple[bool, ...]:  # type: ignore[no-untyped-def]
        values = list(image.tobytes())
        return tuple(
            values[y * 9 + x] > values[y * 9 + x + 1]
            for y in range(8)
            for x in range(8)
        )

    def _translation_tolerant_mae(
        self, reference: list[float], candidate: list[float],
    ) -> tuple[float, float]:
        size = self._policy.visual_thumbnail_size
        radius = self._policy.visual_alignment_radius
        best: tuple[float, float] | None = None
        block_size = size // 4
        for dy in range(-radius, radius + 1):
            y_start = max(0, -dy)
            y_stop = min(size, size - dy)
            for dx in range(-radius, radius + 1):
                x_start = max(0, -dx)
                x_stop = min(size, size - dx)
                total = 0.0
                count = 0
                block_totals = [0.0] * 16
                block_counts = [0] * 16
                for y in range(y_start, y_stop):
                    ref_row = y * size
                    cand_row = (y + dy) * size
                    for x in range(x_start, x_stop):
                        diff = abs(reference[ref_row + x] - candidate[cand_row + x + dx])
                        total += diff
                        count += 1
                        block = (y // block_size) * 4 + (x // block_size)
                        block_totals[block] += diff
                        block_counts[block] += 1
                if count == 0:
                    continue
                g = total / (count * 255)
                b = max(
                    (t / (c * 255) for t, c in zip(block_totals, block_counts, strict=True) if c),
                    default=0.0,
                )
                score = (g, b)
                if best is None or score < best:
                    best = score
        if best is None:
            raise ValueError("visual alignment produced no overlapping pixels")
        return best

    # --- quality measurements -------------------------------------------

    @staticmethod
    def _sharpness(thumb: list[float]) -> float | None:
        # Relative sharpness via normalized high-frequency energy (Laplacian-ish
        # neighbor difference). Higher energy = sharper; normalized to [0, 1].
        size = int(math.isqrt(len(thumb)))
        if size < 3:
            return None
        energy = 0.0
        count = 0
        for y in range(1, size - 1):
            for x in range(1, size - 1):
                idx = y * size + x
                center = thumb[idx]
                energy += abs(center - thumb[idx - 1])
                energy += abs(center - thumb[idx + 1])
                energy += abs(center - thumb[idx - size])
                energy += abs(center - thumb[idx + size])
                count += 4
        if count == 0:
            return None
        # Normalize: mean neighbor difference / 255, then scaled into [0, 1].
        normalized = (energy / count) / 255.0
        return max(0.0, min(1.0, normalized * 4.0))

    @staticmethod
    def _luminance(thumb: list[float]) -> float | None:
        if not thumb:
            return None
        return (sum(thumb) / len(thumb)) / 255.0

    @staticmethod
    def _clipping(thumb: list[float], *, high: bool) -> float | None:
        if not thumb:
            return None
        threshold = 245.0 if high else 10.0
        clipped = sum(1 for v in thumb if (v >= threshold if high else v <= threshold))
        return clipped / len(thumb)


def _open_image(observation: Observation):  # type: ignore[no-untyped-def]
    from PIL import Image

    return Image.open(BytesIO(observation.preview.bytes_))


def _gaussian_blur(radius: float):  # type: ignore[no-untyped-def]
    from PIL import ImageFilter

    return ImageFilter.GaussianBlur(radius)


__all__ = [
    "PILFrameSignalComputer",
]
