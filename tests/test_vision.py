import io

import pytest
from PIL import Image

from pikvm_mcp.vision import Region, crop_jpeg, validate_region


def _jpeg(width: int = 100, height: int = 50) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def test_crop_uses_normalized_coordinates():
    cropped, bounds = crop_jpeg(_jpeg(), Region(0.25, 0.2, 0.5, 0.6))

    with Image.open(io.BytesIO(cropped)) as image:
        assert image.size == (50, 30)
    assert bounds == (25, 10, 75, 40)


@pytest.mark.parametrize("values", [(-0.1, 0, 1, 1), (0, 0, 0, 1), (0.5, 0.5, 0.6, 0.5)])
def test_region_rejects_invalid_normalized_bounds(values):
    with pytest.raises(ValueError):
        validate_region(*values)
