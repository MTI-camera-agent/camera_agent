from __future__ import annotations

import pytest

from models.factory import build_image_generator, build_structured_vision_client


def test_structured_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown structured vision provider"):
        build_structured_vision_client({"provider": "missing"})


def test_image_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown image provider"):
        build_image_generator({"provider": "missing"})
