from PIL import Image, ImageDraw

from order_ocr.ocr import _is_strong_ocr_candidate, _score_ocr_text, _windows_language_tags, preprocess_image_variants


def test_windows_language_tags_include_chinese_and_english_by_default():
    assert _windows_language_tags("eng+chi_sim")[:2] == ["zh-Hans-CN", "zh-Hans"]
    assert "en-US" in _windows_language_tags("eng+chi_sim")


def test_ocr_score_prefers_clean_english_over_garbled_profile_text():
    clean = "OCR unavailable Tesseract OCR was not found. Install it or set TESSERACT CMD."
    garbled = "OCR unavailable Tesseract OCR W\u00f65 not 0 \u51f5 n \u5fd2 TESSERACT CMD."

    assert _score_ocr_text(clean) > _score_ocr_text(garbled)


def test_ocr_score_prefers_chinese_order_signal_over_app_ui_text():
    chinese_order = (
        "\u5546\u54c1\u4fe1\u606f \u6d77\u5929\u9c9c\u5473\u751f\u62bd "
        "\u5355\u4ef7: $4.49 \u6570\u91cf: 1 "
        "\u97e9\u56fd\u5c16\u6912 \u5355\u4ef7: $4.99 \u6570\u91cf: 1"
    )
    ui_heavy = "Order Screenshot Recognizer Workbook OCR Text Save All Detected Items Browse Reload"

    assert _score_ocr_text(chinese_order) > _score_ocr_text(ui_heavy)


def test_preprocess_image_variants_include_chinese_friendly_candidates():
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 600, 92), outline=(180, 180, 180), width=2)
    draw.line((60, 68, 460, 68), fill=(90, 90, 90), width=2)
    draw.line((60, 145, 520, 145), fill=(120, 120, 120), width=1)

    variants = preprocess_image_variants(image)

    names = {name for name, _ in variants}
    assert "full-sharp" in names
    assert "full-threshold" in names
    assert "full-unsharp" in names
    assert any(img.width > image.width or img.height > image.height for _, img in variants)


def test_ocr_score_prefers_order_body_over_browser_noise():
    order_body = (
        "\u6d77\u5929 \u9c9c\u5473\u751f\u62bd 1900\u6beb\u5347 \u5355\u4ef7: $4.49 \u6570\u91cf: 1 "
        "\u767d\u6885 \u65e5\u5f0f\u7cef\u7c73 5\u78c5 \u5355\u4ef7: $10.49 \u6570\u91cf: 1"
    )
    noisy_browser = (
        "search Apps Home OneDrive PubMed github Amazon reload clipboard workbook "
        "$4.49 $10.49 Order Screenshot Recognizer"
    )

    assert _score_ocr_text(order_body) > _score_ocr_text(noisy_browser)


def test_strong_ocr_candidate_accepts_marketplace_order_blocks():
    text = (
        "SMART&CASUAL Cotton Twine Sold by: Smart & Casual Return items: Eligible through July 17, 2026 $5.99 "
        "BENFEI USB C to HDMI Cable Sold by: BenfeiDirect Return items: Eligible through July 17, 2026 $6.99"
    )

    assert _is_strong_ocr_candidate(text)


def test_marketplace_side_rail_noise_does_not_short_circuit_ocr():
    clean = (
        "SMART&CASUAL Cotton Twine Sold by: Smart & Casual Return items: Eligible through July 17, 2026 $5.99 "
        "BENFEI USB C to HDMI Cable Sold by: BenfeiDirect Return items: Eligible through July 17, 2026 $6.99"
    )
    noisy = "WHOLE FOODS 2 items $2.98 Add $22.02 for FREE delivery Co to Cart $1.49 " + clean

    assert _is_strong_ocr_candidate(clean)
    assert not _is_strong_ocr_candidate(noisy)
    assert _score_ocr_text(clean) > _score_ocr_text(noisy)


def test_preprocess_image_variants_include_browser_order_body_crops():
    image = Image.new("RGB", (1800, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((360, 220, 1280, 900), outline=(180, 180, 180), width=3)
    draw.text((500, 320), "SMART&CASUAL Cotton Twine", fill=(20, 20, 20))
    draw.text((500, 360), "Sold by: Smart Casual", fill=(20, 20, 20))
    draw.text((1680, 220), "Go to Cart", fill=(20, 20, 20))

    names = {name for name, _ in preprocess_image_variants(image)}

    assert "browser-order-main-sharp" in names
    assert "browser-order-list-sharp" in names
    assert "no-right-rail-sharp" in names
