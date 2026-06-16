from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageEnhance, ImageFilter, ImageGrab, ImageOps


class OCRUnavailable(RuntimeError):
    """Raised when no local OCR engine can be used."""


COMMON_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

WINDOWS_OCR_SCRIPT = Path(__file__).with_name("windows_ocr.ps1")
ORDER_KEYWORDS = (
    "amount",
    "date",
    "item",
    "line item",
    "order",
    "paid",
    "payment",
    "price",
    "product",
    "qty",
    "quantity",
    "receipt",
    "subtotal",
    "total",
    "unit price",
    "\u4e0b\u5355",
    "\u4ef7\u683c",
    "\u5546\u54c1",
    "\u5546\u54c1\u4fe1\u606f",
    "\u65e5\u671f",
    "\u652f\u4ed8",
    "\u5b9e\u4ed8",
    "\u6570\u91cf",
    "\u603b\u8ba1",
    "\u5355\u4ef7",
    "\u8ba2\u5355",
    "\u8d2d\u4e70",
    "\u91d1\u989d",
)

UI_NOISE_KEYWORDS = (
    "capture screen",
    "clear",
    "detected items",
    "ocr clipboard",
    "ocr language",
    "ocr text",
    "open image",
    "order screenshot recognizer",
    "parse text",
    "save all",
    "save to workbook",
    "update item",
    "workbook",
)


def find_tesseract() -> str | None:
    env_path = os.environ.get("TESSERACT_CMD")
    if env_path and Path(env_path).exists():
        return env_path

    found = shutil.which("tesseract")
    if found:
        return found

    for path in COMMON_TESSERACT_PATHS:
        if Path(path).exists():
            return path
    return None


def find_powershell() -> str | None:
    if os.name != "nt":
        return None
    return shutil.which("powershell.exe") or shutil.which("powershell")


def capture_screen() -> Image.Image:
    try:
        return ImageGrab.grab(all_screens=True)
    except TypeError:
        return ImageGrab.grab()


def image_from_clipboard() -> Image.Image | None:
    data = ImageGrab.grabclipboard()
    if isinstance(data, Image.Image):
        return data
    if isinstance(data, list):
        for item in data:
            path = Path(item)
            if path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
                return Image.open(path)
    return None


def preprocess_image(image: Image.Image) -> Image.Image:
    return preprocess_image_variants(image)[0][1]


def preprocess_image_variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    variants: list[tuple[str, Image.Image]] = []
    for region_name, region in _ocr_regions(image):
        base = _scaled_gray(region)
        auto = ImageOps.autocontrast(base)
        variants.append((f"{region_name}-gray", base))
        variants.append((f"{region_name}-autocontrast", auto))

        contrast = ImageEnhance.Contrast(auto).enhance(1.85)
        sharp = ImageEnhance.Sharpness(contrast).enhance(1.55)
        variants.append((f"{region_name}-sharp", sharp))

        unsharp = sharp.filter(ImageFilter.UnsharpMask(radius=1.4, percent=145, threshold=3))
        variants.append((f"{region_name}-unsharp", unsharp))

        threshold = ImageEnhance.Contrast(auto).enhance(2.2).point(lambda pixel: 255 if pixel >= 172 else 0)
        variants.append((f"{region_name}-threshold", threshold.convert("L")))

    return _dedupe_image_variants(variants)


def _ocr_regions(image: Image.Image) -> list[tuple[str, Image.Image]]:
    source = image.convert("RGB")
    width, height = source.size
    regions: list[tuple[str, Image.Image]] = [("full", source)]

    if height >= 500:
        top_crop = int(height * 0.07)
        if 0 < top_crop < height // 3:
            regions.append(("no-top-ui", source.crop((0, top_crop, width, height))))

    if width >= 900:
        side_crop = int(width * 0.035)
        if side_crop > 0:
            regions.append(("trim-sides", source.crop((side_crop, 0, width - side_crop, height))))

    return regions


def _scaled_gray(image: Image.Image) -> Image.Image:
    work = ImageOps.grayscale(image)
    width, height = work.size
    long_edge = max(width, height)
    if long_edge < 1200:
        scale = 3.0
    elif long_edge < 1900:
        scale = 2.0
    else:
        scale = 1.0

    if scale != 1.0:
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        work = work.resize(new_size, resampling)
    return work


def _dedupe_image_variants(variants: list[tuple[str, Image.Image]]) -> list[tuple[str, Image.Image]]:
    seen: set[tuple[tuple[int, int], bytes]] = set()
    unique: list[tuple[str, Image.Image]] = []
    for name, image in variants:
        sample = image.resize((min(32, image.width), min(32, image.height))).tobytes()
        key = (image.size, sample)
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, image))
    return unique


def _language_attempts(languages: str) -> Iterable[str]:
    yield languages
    if languages != "eng":
        yield "eng"


def _windows_language_tags(languages: str) -> list[str]:
    requested = languages.casefold()
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    wants_chinese = any(token in requested for token in ("chi", "zh", "cn", "auto"))
    wants_english = any(token in requested for token in ("eng", "en", "auto"))

    if wants_chinese:
        add("zh-Hans-CN")
        add("zh-Hans")
        add("zh-CN")
    if wants_english:
        add("en-US")
    if not tags:
        add("zh-Hans-CN")
        add("en-US")
    return tags


def ocr_image(image: Image.Image | Path | str, languages: str = "eng+chi_sim") -> str:
    cleanup_paths: list[Path] = []
    if isinstance(image, (str, Path)):
        original_path = Path(image)
        source = Image.open(original_path)
    else:
        source = image
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        original_path = Path(handle.name)
        source.save(original_path)
        cleanup_paths.append(original_path)

    variant_paths: list[tuple[str, Path]] = []
    for name, variant in preprocess_image_variants(source):
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.close()
        variant_path = Path(handle.name)
        variant.save(variant_path)
        cleanup_paths.append(variant_path)
        variant_paths.append((name, variant_path))

    try:
        candidates: list[str] = []
        tesseract = find_tesseract()
        if tesseract:
            for _, variant_path in variant_paths:
                try:
                    text = _ocr_with_tesseract(tesseract, variant_path, languages)
                except OCRUnavailable:
                    text = ""
                _add_ocr_candidate(candidates, text)

        text = _ocr_with_windows(original_path, languages)
        _add_ocr_candidate(candidates, text)

        for _, variant_path in variant_paths:
            text = _ocr_with_windows(variant_path, languages)
            _add_ocr_candidate(candidates, text)

        if candidates:
            return max(candidates, key=_score_ocr_text)

        raise OCRUnavailable(
            "No OCR engine was available. Install Tesseract OCR, set TESSERACT_CMD, "
            "or paste OCR text manually."
        )
    finally:
        for path in cleanup_paths:
            path.unlink(missing_ok=True)


def _ocr_with_tesseract(tesseract: str, image_path: Path, languages: str) -> str:
    last_error = ""
    for language in _language_attempts(languages):
        proc = subprocess.run(
            [tesseract, str(image_path), "stdout", "-l", language, "--psm", "6"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        last_error = (proc.stderr or proc.stdout or "").strip()
    raise OCRUnavailable(f"Tesseract could not read the image. {last_error}".strip())


def _ocr_with_windows(image_path: Path, languages: str) -> str:
    powershell = find_powershell()
    if not powershell or not WINDOWS_OCR_SCRIPT.exists():
        return ""

    tags = _windows_language_tags(languages)
    proc = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WINDOWS_OCR_SCRIPT),
            "-ImagePath",
            str(image_path),
            "-LanguageTags",
            ",".join(tags),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if proc.returncode != 0:
        return ""

    try:
        payload = json.loads(proc.stdout.strip() or "[]")
    except json.JSONDecodeError:
        return proc.stdout.strip()

    if isinstance(payload, dict):
        payload = [payload]
    candidates = [
        str(entry.get("text", "")).strip()
        for entry in payload
        if isinstance(entry, dict) and str(entry.get("text", "")).strip()
    ]
    if not candidates:
        return ""
    return max(candidates, key=_score_ocr_text)


def _add_ocr_candidate(candidates: list[str], text: str) -> None:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return
    if any(re.sub(r"\s+", " ", candidate).strip() == normalized for candidate in candidates):
        return
    candidates.append(text.strip())


def _score_ocr_text(text: str) -> float:
    lowered = text.casefold()
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z]", text))
    digits = len(re.findall(r"\d", text))
    prices = len(re.findall(r"[$\u00a5\uffe5]\s*\d(?:\s*[,.．·]\s*\d{1,2}|\s+\d\s*\d)?|\d+\.\d{2}", text))
    dates = len(re.findall(r"\d{4}[-/\u5e74]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", text))
    keyword_hits = sum(1 for keyword in ORDER_KEYWORDS if keyword in lowered)
    line_item_hits = len(
        re.findall(r"(?:\u5355\s*\u4ef7|\u5355\s*[1il]?\s*[\u98e0\u98df]|unit\s*price|price)\s*[:\uff1a]?", lowered)
    )
    quantity_hits = len(re.findall(r"(?:\u6570\s*\u91cf|\u6578\s*\u91cf|\u91cc|qty|quantity)\s*[:\uff1a.]?", lowered))
    ui_noise_hits = sum(1 for keyword in UI_NOISE_KEYWORDS if keyword in lowered)
    browser_noise_hits = len(
        re.findall(r"(?:amazon|onedrive|pubmed|github|search|mywebpage|documents|browser|reload|clipboard)", lowered)
    )
    chinese_units = len(re.findall(r"(?:\u6beb\s*\u5347|\u78c5|\u514b|\u679a|\u74f6|\u888b|\u76ce\s*\u53f8|\u5347)", text))
    food_terms = len(
        re.findall(
            r"(?:\u751f\s*\u62bd|\u8001\s*\u62bd|\u8c46\s*\u6c99|\u86cb\s*\u7cd5|\u5c16\s*\u6912|\u4e94\s*\u82b1|\u7cef\s*\u7c73|\u8fa3\s*\u6912|\u9171|\u918b)",
            text,
        )
    )
    odd_chars = len(re.findall(r"[^\x00-\x7f\u4e00-\u9fff\s$￥¥.,:：;；/\\\-()\[\]{}|·．，。]", text))
    compact_len = min(len(re.sub(r"\s+", "", text)), 1000)
    paired_line_bonus = min(line_item_hits, quantity_hits) * 24
    return (
        cjk * 2.8
        + letters * 1.0
        + digits * 1.4
        + prices * 20
        + dates * 12
        + keyword_hits * 10
        + line_item_hits * 20
        + quantity_hits * 14
        + paired_line_bonus
        + chinese_units * 6
        + food_terms * 8
        + compact_len * 0.03
        - odd_chars * 2
        - ui_noise_hits * 10
        - browser_noise_hits * 6
    )
