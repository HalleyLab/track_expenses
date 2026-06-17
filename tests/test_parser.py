from datetime import date

from order_ocr.parser import ReferenceData, choose_category, parse_order_text


def test_parse_order_text_with_reference_match():
    reference = ReferenceData(
        categories=["Daily Necessities", "Drinks"],
        item_category={"Dove Body Wash": "Daily Necessities"},
    )
    text = """
    Order placed June 15, 2026
    Dove Body Wash
    Order total $5.99
    """

    candidate = parse_order_text(text, reference, today=date(2026, 6, 16))

    assert candidate.item == "Dove Body Wash"
    assert candidate.purchase_date == date(2026, 6, 15)
    assert candidate.price == 5.99
    assert candidate.category == "Daily Necessities"
    assert not candidate.needs_purchase_date


def test_parse_order_text_missing_date_needs_manual_entry():
    reference = ReferenceData(categories=["Protein"], item_category={})
    text = """
    Chicken Breast Fillets
    Total $10.92
    """

    candidate = parse_order_text(text, reference, today=date(2026, 6, 16))

    assert candidate.item == "Chicken Breast Fillets"
    assert candidate.price == 10.92
    assert candidate.category == "Protein"
    assert candidate.needs_purchase_date


def test_parse_multiple_chinese_items_with_unit_price_and_quantity():
    reference = ReferenceData(
        categories=["Sauce", "Carbonhydrate", "Snacks"],
        item_category={},
    )
    text = (
        "\u6d77 \u5929 \u918b \u5473 \u751f \u62bd 1900 \u6beb \u5347 "
        "\u5355 \u4ef7\uff1a $ 4 . 49 ] \u6570 \u91cf\uff1a 1 "
        "\u6c6a \u8001 \u5317 \u4eac \u8001 \u5473 \u6c64 \u9762 5 \u5305 "
        "\u5355\u4ef7\uff1a$2.99 \u6570\u91cf\uff1a2 "
        "2026-06-17"
    )

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert candidate.purchase_date == date(2026, 6, 17)
    assert len(candidate.lines) == 2
    assert candidate.lines[0].item == "\u6d77\u5929\u918b\u5473\u751f\u62bd1900\u6beb\u5347"
    assert candidate.lines[0].unit_price == 4.49
    assert candidate.lines[0].quantity == 1
    assert candidate.lines[0].price == 4.49
    assert candidate.lines[0].category == "Sauce"
    assert candidate.lines[1].item == "\u6c6a\u8001\u5317\u4eac\u8001\u5473\u6c64\u97625\u5305"
    assert candidate.lines[1].unit_price == 2.99
    assert candidate.lines[1].quantity == 2
    assert candidate.lines[1].price == 5.98
    assert candidate.lines[1].category == "Carbonhydrate"
    assert candidate.price == 10.47


def test_parse_chinese_items_when_quantity_label_is_missing():
    reference = ReferenceData(
        categories=["Sauce", "Protein"],
        item_category={},
    )
    text = "海天鲜味生抽 单价：$4.49 1 韩国尖椒 1 磅 单价：$4.99 1 猪五花肉 单价：$6.68 1"

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert len(candidate.lines) == 3
    assert candidate.lines[0].item == "海天鲜味生抽"
    assert candidate.lines[0].price == 4.49
    assert candidate.lines[0].category == "Sauce"
    assert candidate.lines[1].item == "韩国尖椒1磅"
    assert candidate.lines[1].price == 4.99
    assert candidate.lines[1].category == "Sauce"
    assert candidate.lines[2].item == "猪五花肉"
    assert candidate.lines[2].price == 6.68
    assert candidate.lines[2].category == "Protein"


def test_semantic_category_rules_match_food_groups():
    reference = ReferenceData(
        categories=["Protein", "Vegetables", "Sauce", "Carbonhydrate", "Daily Necessities", "Drinks"],
        item_category={"Milk": "Drinks"},
    )

    cases = {
        "牛奶": "Protein",
        "鸡蛋 12枚": "Protein",
        "Fresh Chicken Thighs": "Protein",
        "苹果 香蕉 西兰花": "Vegetables",
        "生抽 老抽 料酒": "Sauce",
        "火锅底料": "Sauce",
        "王致和 豆沙 500克": "Sauce",
        "老干妈 辣椒酱": "Sauce",
        "李锦记 特级老抽": "Sauce",
        "韩国尖椒 1 磅": "Sauce",
        "青椒": "Sauce",
        "辣椒": "Sauce",
        "干辣椒": "Sauce",
        "花椒 麻椒 八角": "Sauce",
        "葱姜蒜": "Sauce",
        "糯米 面粉 淀粉": "Carbonhydrate",
        "Thin Spaghetti Pasta": "Carbonhydrate",
        "洗发水 牙膏 纸巾": "Daily Necessities",
    }

    for item, expected in cases.items():
        category, score = choose_category(item, reference)
        assert category == expected
        assert score >= 0.55


def test_unknown_item_does_not_default_to_daily_necessities():
    reference = ReferenceData(categories=["Daily Necessities", "Protein"], item_category={})

    category, score = choose_category("mystery imported bundle", reference)

    assert category is None
    assert score == 0.0


def test_smart_category_ignores_balance_history_and_category_list():
    reference = ReferenceData(categories=[], item_category={"\u725b\u5976": "Drinks"})

    category, score = choose_category("\u725b\u5976", reference)

    assert category == "Protein"
    assert score >= 0.55


def test_parse_common_chinese_ocr_unit_price_misreads():
    reference = ReferenceData(categories=[], item_category={})
    text = (
        "\u738b\u81f4\u548c\u8c46\u6c99500\u514b "
        "\u5355 1 \u98e0 $ 4 2 g \u91cc 1 "
        "\u97e9\u56fd\u5c16\u69121\u78c5 \u5355 1 \u98e0 $ 4 9 9 \u91cc 1 "
        "\u732a\u4e94\u82b1\u8089 \u5355 1 \u98e0 $ 6 6 8 \u91cc 1"
    )

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert len(candidate.lines) == 3
    assert candidate.lines[0].item == "\u738b\u81f4\u548c\u8c46\u6c99500\u514b"
    assert candidate.lines[0].unit_price == 4.29
    assert candidate.lines[0].category == "Sauce"
    assert candidate.lines[1].item == "\u97e9\u56fd\u5c16\u69121\u78c5"
    assert candidate.lines[1].unit_price == 4.99
    assert candidate.lines[1].category == "Sauce"
    assert candidate.lines[2].item == "\u732a\u4e94\u82b1\u8089"
    assert candidate.lines[2].unit_price == 6.68
    assert candidate.lines[2].category == "Protein"


def test_price_noise_row_is_not_treated_as_item():
    reference = ReferenceData(categories=[], item_category={})
    text = "$4.49 $2.99 $7.49 \u5355\u4ef7\uff1a$4.29 \u6570\u91cf\uff1a1"

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert candidate.lines == []


def test_parse_sayweee_chinese_order_rows_with_ocr_noise():
    reference = ReferenceData(categories=[], item_category={})
    text = (
        "0 \u6d77 \u5929 \u9c9c \u5473 \u751f \u62bd \u5927 \u6876 \u88c5 1900 \u6beb \u5347 "
        "\u5355 \u4ef7 \uff1a $ 4 \uff0e 49 1 \u6570 \u91cf \uff0e 1 "
        "\u4e8c \u6d0b \u8001 \u5317 \u4eac \u8001 \u5473 \u9053 \u8702 \u871c \u86cb \u7cd5 "
        "\u3016 \u7ae5 \u5e74 \u7684 \u8bb0 \u5fc6 \u3017 19 \u679a 600 \u514b "
        "\u5355 \u4ef7 \uff1a $ 2 \uff0e 99 1 \u6570 \u91cf \uff1a 1 "
        "\u738b \u81f4 \u548c \u8c46 \u6c99 500 \u514b "
        "\u5355 \u4ef7 \uff1a $ 4 \uff0e 29 1 \u6570 \u91cf \uff1a 1 "
        "\u674e \u9526 \u8bb0 \u7279 \u7ea7 \u8001 \u62bd \u5927 \u6876 \u88c5 1 \uff0c 75 \u5347 59 \u6db2 \u76ce \u53f8 "
        "\u5355 \u4ef7 \uff1a $ 7 \uff0e 49 1 \u6570 \u91cf \uff1a 1 "
        "\u97e9 \u56fd \u5c16 \u6912 1 \u78c5 "
        "\u5355 \u4ef7 \uff1a $ 4 \uff0e 99 1 \u6570 \u91cf \uff0e 1 "
        "\u732a \u4e94 \u82b1 \u8089 \uff0c \u97e9 \u5f0f \u5207 \u7247 10mm, \u51b7 \u51bb 1 \u78c5 "
        "\u5355 \u4ef7 \uff1a $ 6 \uff0e 68 1 \u6570 \u91cf \uff1a 1 "
        "\u767d \u6885 \u65e5 \u5f0f \u7cef \u7c73 5 \u78c5 "
        "\u5355 \u4ef7 \uff1a $ 10 \uff0e 49 \u4e28 \u6570 \u91cf "
        "$ 4 \uff0c 49 $ 2 \uff0c 99 $ 4 \uff0c 29 $ 7 \uff0c 49 $ 4 \uff0c 99 $ 6 \uff0c 68 $ 10 \uff0c 49"
    )

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert len(candidate.lines) == 7
    assert candidate.lines[0].item == "\u6d77\u5929\u9c9c\u5473\u751f\u62bd\u5927\u6876\u88c51900\u6beb\u5347"
    assert candidate.lines[0].unit_price == 4.49
    assert candidate.lines[0].category == "Sauce"
    assert not candidate.lines[1].item.startswith("\u6570\u91cf")
    assert "\u86cb\u7cd5" in candidate.lines[1].item
    assert candidate.lines[1].unit_price == 2.99
    assert candidate.lines[1].category == "Snacks"
    assert candidate.lines[2].item == "\u738b\u81f4\u548c\u8c46\u6c99500\u514b"
    assert candidate.lines[2].category == "Sauce"
    assert candidate.lines[3].unit_price == 7.49
    assert candidate.lines[3].category == "Sauce"
    assert candidate.lines[4].item == "\u97e9\u56fd\u5c16\u69121\u78c5"
    assert candidate.lines[4].category == "Sauce"
    assert candidate.lines[5].unit_price == 6.68
    assert candidate.lines[5].category == "Protein"
    assert candidate.lines[6].item == "\u767d\u6885\u65e5\u5f0f\u7cef\u7c735\u78c5"
    assert candidate.lines[6].unit_price == 10.49
    assert candidate.lines[6].quantity == 1
    assert candidate.lines[6].category == "Carbonhydrate"


def test_parse_browser_noisy_order_rows_and_spaced_cent_prices():
    reference = ReferenceData(categories=[], item_category={})
    text = (
        "search Apps Home OneDrive sayweee.com order detail Amazon.com H "
        "\u6d77 \u5929 \u9c9c \u5473 \u751f \u62bd \u5927 \u6876 \u88c5 1900 \u6beb \u5347 "
        "\u5355 \u4ef7 \uff1a $ 4 . 49 \u6570 \u91cf \uff1a 1 "
        "\u4e8c \u6d0b \u8001 \u5317 \u4eac \u8001 \u5473 \u9053 \u8702 \u871c \u86cb \u7cd5 "
        "\u7ae5 \u5e74 \u7684 \u8bb0 \u5fc6 19 \u679a 500 \u514b "
        "\u5355 \u4ef7 \uff1a $ 2 . 99 \u6570 \u91cf \uff1a 1 "
        "\u738b \u81f4 \u548c \u8c46 \u6c99 500 \u514b "
        "\u5355 \u4ef7 \uff1a $ 4 . 29 \u6570 \u91cf \uff1a 1 "
        "\u674e \u9526 \u8bb0 \u7279 \u7ea7 \u8001 \u62bd \u5927 \u6876 \u88c5 1 . 75 \u5347 59 \u6db2 \u76ce\u53f8 "
        "\u5355 \u4ef7 \uff1a $ 7 . 49 \u6570\u91cf \uff1a 1 "
        "\u97e9 \u56fd \u5c16 \u6912 1 \u78c5 "
        "\u5355 \u4ef7 \uff1a $ 4 . 99 \u6570 \u91cf \uff1a 1 "
        "\u732a \u4e94 \u82b1 \u8089 \u97e9 \u7247 10mm \u51b7 1 \u78c5 "
        "\u5355 \u4ef7 \uff1a $ 6 . 58 \u6570 \u91cf \uff1a 1 "
        "\u767d \u6885 \u65e5 \u5f0f \u7cef \u7c73 5 \u78c5 "
        "\u5355 \u4ef7 \uff1a $ 1 49 \u6570 \u91cf \uff1a 1"
    )

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert len(candidate.lines) == 7
    assert candidate.lines[0].item == "\u6d77\u5929\u9c9c\u5473\u751f\u62bd\u5927\u6876\u88c51900\u6beb\u5347"
    assert candidate.lines[0].unit_price == 4.49
    assert candidate.lines[0].category == "Sauce"
    assert candidate.lines[1].category == "Snacks"
    assert candidate.lines[6].item == "\u767d\u6885\u65e5\u5f0f\u7cef\u7c735\u78c5"
    assert candidate.lines[6].unit_price == 10.49
    assert candidate.lines[6].category == "Carbonhydrate"


def test_parse_chinese_comma_as_price_and_quantity_separator():
    reference = ReferenceData(categories=[], item_category={})
    text = (
        "\u6d77 \u5929 \u9c9c \u5473 \u751f \u62bd \u5927 \u6876 \u88c5 1900 \u6beb \u5347 "
        "\u5355 \u4ef7 \uff1a $ 4 \uff0c 49 | \u6570 \u91cf \uff0c 1 "
        "\u767d \u6885 \u65e5 \u5f0f \u7cef \u7c73 5 \u78c5 "
        "\u5355 \u4ef7 \uff1a $ 10 \uff0c 49 | \u6570 \u91cf 1"
    )

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert len(candidate.lines) == 2
    assert candidate.lines[0].item == "\u6d77\u5929\u9c9c\u5473\u751f\u62bd\u5927\u6876\u88c51900\u6beb\u5347"
    assert candidate.lines[0].unit_price == 4.49
    assert candidate.lines[0].quantity == 1
    assert candidate.lines[0].category == "Sauce"
    assert candidate.lines[1].item == "\u767d\u6885\u65e5\u5f0f\u7cef\u7c735\u78c5"
    assert candidate.lines[1].unit_price == 10.49
    assert candidate.lines[1].category == "Carbonhydrate"


def test_parse_amazon_delivered_items_without_unit_price_labels():
    reference = ReferenceData(categories=[], item_category={})
    text = (
        "Delivered today Your package was delivered. It was handed directly to a resident. "
        "Get product support Track package Return or replace items Share gift receipt Leave seller feedback "
        "Write a product review qtJ 01 ET SMART&CASUAL 600 Feet 2mm Cotton Butcher Twine String Soft Food Safe for "
        "Cooking Craft Baker Kitchen Meat Turkey Sausage Roasting Gift Wrapping Gardening Crocheting Knitting "
        "Sold by: Smart & Casual Return or replace items: Eligible through July 17, 2026 Ss.gg "
        "Buy it again View your item BENFEI USB C to HDMI 6 Feet Cable [4K@60Hz, Aluminium Shell, Nylon Braided], "
        "USB Type-C to HDMI Cable [Thunderbolt 3/4/5] Compatible for MacBook Pro/Air/iPad Pro 2023/2022/2021/2020/2019, Gray "
        "Sold by: BenfeiDirect Return or replace items: Eligible through July 17, 2026 $6.gg "
        "Buy it again View your item Diet Coke Diet Soda, 16.9 fl oz Bottles, 6 Pack - Cola Soft Drinks "
        "Sold by: Amazon.com Return items: Eligible through July 17, 2026 $5.37 "
        "Buy it again View your item Sprite Zero Sugar Lemon Lime Diet Soda Pop Soft Drinks, 16.9 fl oz, 6 Pack "
        "Sold by: Amazon.com Return items: Eligible through July 17, 2026 $5.37 "
        "Buy it again View your item"
    )

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert candidate.purchase_date is None
    assert candidate.needs_purchase_date
    assert len(candidate.lines) == 4
    assert candidate.lines[0].item.startswith("SMART&CASUAL 600 Feet")
    assert candidate.lines[0].unit_price == 5.99
    assert candidate.lines[0].category == "Daily Necessities"
    assert "BENFEI USB C to HDMI" in candidate.lines[1].item
    assert candidate.lines[1].unit_price == 6.99
    assert candidate.lines[1].category == "Electronics"
    assert candidate.lines[2].item.startswith("Diet Coke Diet Soda")
    assert candidate.lines[2].unit_price == 5.37
    assert candidate.lines[2].category == "Drinks"
    assert candidate.lines[3].item.startswith("Sprite Zero Sugar")
    assert candidate.lines[3].unit_price == 5.37
    assert candidate.lines[3].category == "Drinks"


def test_parse_noisy_web_order_sold_by_blocks_with_cart_noise():
    reference = ReferenceData(categories=[], item_category={})
    text = (
        "Order Details Ask Gemini MyWebpage QILLLAB Documents JHU Neuroscience "
        "Delivered today Your package was delivered. It was handed directly to a resident. "
        "Get product support Track package Return or replace items Share gift receipt Leave seller feedback "
        "Write a product review Get product support Track package Return or replace items All Bookmarks WHOLE "
        "June 2 items $2.98 Add $22.02 for FREE delivery Go to Cart $1.49 qJ "
        "SMART&CASUAL 600 Feet 2mm Cotton Butcher Twine String Soft Food Safe for Cooking Craft Baker Kitchen Meat Turkey "
        "Sausage Roasting Gift Wrapping Gardening Crocheting Knitting Sold by: Smart Casual "
        "Return or replace items: Eligible through July 17, 2026 S.g Buy it again View your item "
        "BENFEI USB C to HDMI 6 Feet Cable [4K@60Hz, Aluminum Shell, Nylon Braided], USB Type-C to HDMI Cable "
        "[Thunderbolt 3/4/5] Compatible for MacBook Pro/Air/iPad Pro 2023/2022/2021 /2020/2019, Gray "
        "Sold by: BenfeiDirect Return or replace items: Eligible through July 17, 2026 $6.gg Buy it again View your item "
        "Diet Coke Diet Soda, 16.9 fl Oz Bottles, 6 Pack - Cola Soft Drinks Sold by: Amazon.com "
        "Return items: Eligible through July 17, 2026 $5.37 Buy it again View your item "
        "Sprite Zero Sugar Lemon Lime Diet Soda Pop Soft Drinks, 16.9 fl Oz, 6 Pack Sold by: Amazon.com "
        "Return items: Eligible through July 17, 2026 $5.37 Buy it again View your item "
        "Delivered today Your package was delivered. 17 Sparkle Pick-A-Size Paper Towels, 6 Double Rolls"
    )

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert candidate.purchase_date is None
    assert len(candidate.lines) == 4
    assert candidate.lines[0].item.startswith("SMART&CASUAL 600 Feet")
    assert "Go to Cart" not in candidate.lines[0].item
    assert "$1.49" not in candidate.lines[0].item
    assert candidate.lines[0].unit_price == 5.99
    assert candidate.lines[1].item.startswith("BENFEI USB C to HDMI")
    assert candidate.lines[1].unit_price == 6.99
    assert candidate.lines[2].item.startswith("Diet Coke Diet Soda")
    assert candidate.lines[3].item.startswith("Sprite Zero Sugar")
    assert all(line.item != "Leave" for line in candidate.lines)
    assert all("Sparkle" not in line.item for line in candidate.lines)


def test_parse_generic_web_seller_and_merchant_blocks():
    reference = ReferenceData(categories=[], item_category={})
    text = (
        "Delivered Organic Bananas 3 lb Bag Seller: Fresh Market Return window closes July 1, 2026 $3.49 Add to cart "
        "USB-C Fast Charging Cable 6 ft Merchant: Tech Shop Delivered yesterday $8.99 Reorder"
    )

    candidate = parse_order_text(text, reference, today=date(2026, 6, 17))

    assert len(candidate.lines) == 2
    assert candidate.lines[0].item.startswith("Organic Bananas")
    assert candidate.lines[0].unit_price == 3.49
    assert candidate.lines[0].category == "Vegetables"
    assert candidate.lines[1].item.startswith("USB-C Fast Charging Cable")
    assert candidate.lines[1].unit_price == 8.99
    assert candidate.lines[1].category == "Electronics"
