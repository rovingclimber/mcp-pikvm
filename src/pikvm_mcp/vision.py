"""Small, on-demand image helpers for the standalone MCP server.

This is deliberately not a continuous observer. OCR executes only when its
tool is called and downscales the supplied crop before invoking Tesseract.
"""

from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class Region:
    x: float
    y: float
    width: float
    height: float


def validate_region(x: float, y: float, width: float, height: float) -> Region:
    if not 0.0 <= x < 1.0 or not 0.0 <= y < 1.0 or not 0.0 < width <= 1.0 or not 0.0 < height <= 1.0:
        raise ValueError("Region must use normalized x/y/width/height values from 0 to 1.")
    if x + width > 1.0 or y + height > 1.0:
        raise ValueError("The normalized region must stay within the screenshot.")
    return Region(x, y, width, height)


def crop_jpeg(image_data: bytes, region: Region) -> tuple[bytes, tuple[int, int, int, int]]:
    with Image.open(io.BytesIO(image_data)) as image:
        image = image.convert("RGB")
        left = round(region.x * image.width)
        top = round(region.y * image.height)
        right = round((region.x + region.width) * image.width)
        bottom = round((region.y + region.height) * image.height)
        if right <= left or bottom <= top:
            raise ValueError("The selected region is too small at this screenshot resolution.")
        crop = image.crop((left, top, right, bottom))
        output = io.BytesIO()
        crop.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue(), (left, top, right, bottom)


def read_ocr(image_data: bytes, region: Region) -> dict[str, object]:
    cropped, _ = crop_jpeg(image_data, region)
    with Image.open(io.BytesIO(cropped)) as image:
        image = image.convert("RGB")
        # Keep the low-spec deployment predictable: at most roughly 1.2 MP.
        if image.width * image.height > 1_200_000:
            scale = (1_200_000 / (image.width * image.height)) ** 0.5
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        encoded = io.BytesIO()
        image.save(encoded, format="PNG", optimize=True)
        width, height = image.size

    try:
        completed = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "tsv", "--psm", "6"],
            input=encoded.getvalue(),
            capture_output=True,
            timeout=12,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("OCR exceeded its 12-second local processing limit.") from exc
    if completed.returncode != 0:
        raise RuntimeError("Local OCR failed: " + completed.stderr.decode("utf-8", "replace")[:200])

    words: list[dict[str, object]] = []
    lines: list[str] = []
    truncated = False
    for row in csv.DictReader(completed.stdout.decode("utf-8", "replace").splitlines(), delimiter="\t"):
        text = (row.get("text") or "").strip()
        confidence = float(row.get("conf") or -1)
        if not text or confidence < 25:
            continue
        if len(words) >= 500:
            truncated = True
            break
        left, top = int(row["left"]), int(row["top"])
        word_width, word_height = int(row["width"]), int(row["height"])
        words.append({
            "text": text,
            "confidence": round(confidence, 1),
            "x": round(region.x + (left / width) * region.width, 5),
            "y": round(region.y + (top / height) * region.height, 5),
            "width": round((word_width / width) * region.width, 5),
            "height": round((word_height / height) * region.height, 5),
        })
        lines.append(text)
    return {
        "text": " ".join(lines),
        "words": words,
        "word_count": len(words),
        "truncated": truncated,
    }
