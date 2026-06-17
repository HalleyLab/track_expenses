from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Iterable

from dateutil import parser as date_parser


ITEM_HEADER = "\u7269\u54c1"
CATEGORY_HEADER = "\u7c7b\u522b"
PURCHASE_DATE_HEADER = "\u8d2d\u4e70\u65e5\u671f"


@dataclass
class ReferenceData:
    categories: list[str] = field(default_factory=list)
    item_category: dict[str, str] = field(default_factory=dict)

    @property
    def normalized_categories(self) -> dict[str, str]:
        return {normalize_key(category): category for category in self.categories}


@dataclass
class OrderLine:
    item: str
    unit_price: float | None = None
    quantity: float = 1.0
    price: float | None = None
    category: str | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.price is None and self.unit_price is not None:
            self.price = round(self.unit_price * self.quantity, 2)


@dataclass
class OrderCandidate:
    item: str | None = None
    purchase_date: date | None = None
    price: float | None = None
    category: str | None = None
    lines: list[OrderLine] = field(default_factory=list)
    raw_text: str = ""
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def needs_purchase_date(self) -> bool:
        return self.purchase_date is None


NOISE_WORDS = {
    "address",
    "amount",
    "balance",
    "billing",
    "card",
    "category",
    "cash",
    "change",
    "confidence",
    "delivery",
    "detected item",
    "detected items",
    "discount",
    "email",
    "estimated",
    "invoice",
    "order",
    "paid",
    "payment",
    "phone",
    "qty",
    "quantity",
    "receipt",
    "refund",
    "shipping",
    "subtotal",
    "tax",
    "total",
    "tracking",
    "update item",
    "workbook",
    "workbook row",
}

CN_NOISE_WORDS = (
    "\u5730\u5740",
    "\u5408\u8ba1",
    "\u91d1\u989d",
    "\u8ba2\u5355",
    "\u914d\u9001",
    "\u652f\u4ed8",
    "\u7a0e",
    "\u603b\u8ba1",
    "\u7269\u6d41",
    "\u5c0f\u8ba1",
    "\u8fd0\u8d39",
)

BROWSER_NOISE_MARKERS = (
    "amazon.com",
    "documents",
    "github",
    "home",
    "mail",
    "mywebpage",
    "onedrive",
    "order detail",
    "pubmed",
    "sayweee.com",
    "search",
)

PRICE_RE = re.compile(
    r"(?:(?:USD|US\$|RMB|CNY)\s*)?[$\u00a5]?\s*([0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]{1,2})|[0-9]{1,4}\.[0-9]{2})",
    re.IGNORECASE,
)

DATE_PATTERNS = (
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}",
    r"\d{4}\s*\u5e74\s*\d{1,2}\s*\u6708\s*\d{1,2}\s*\u65e5?",
    r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}",
    r"(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\.?\s+\d{1,2},?\s+\d{2,4}",
    r"\d{1,2}\s+(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\.?,?\s+\d{2,4}",
)

DATE_LABELS = (
    "order placed",
    "ordered",
    "purchase date",
    "purchased",
    "date",
    "\u4e0b\u5355",
    "\u8ba2\u5355\u65f6\u95f4",
    "\u8d2d\u4e70\u65e5\u671f",
    "\u8d2d\u4e70",
)

PRICE_PRIORITY = (
    "grand total",
    "order total",
    "total paid",
    "amount paid",
    "payment total",
    "total",
    "\u5b9e\u4ed8",
    "\u652f\u4ed8",
    "\u8ba2\u5355\u603b\u989d",
    "\u603b\u8ba1",
    "\u5408\u8ba1",
    "\u91d1\u989d",
)

KEYWORDS_BY_CATEGORY = {
    "Carbonhydrate": (
        "bagel",
        "bread",
        "cereal",
        "flour",
        "noodle",
        "pasta",
        "potato",
        "rice",
        "spaghetti",
        "tortilla",
        "\u7c73",
        "\u9762",
        "\u7c89",
        "\u996d",
        "\u997c",
        "\u9ea6",
    ),
    "Daily Necessities": (
        "body wash",
        "butcher twine",
        "cleaner",
        "cotton twine",
        "detergent",
        "dove",
        "food safe string",
        "kitchen twine",
        "paper",
        "saucepan",
        "shampoo",
        "sheet",
        "soap",
        "tissue",
        "toothbrush",
        "toothpaste",
        "towel",
        "twine",
        "\u7eb8",
        "\u6c90\u6d74",
        "\u6d17\u53d1",
        "\u6d17\u8863",
        "\u7259\u818f",
        "\u7259\u5237",
    ),
    "Drinks": (
        "beverage",
        "coffee",
        "coke",
        "drink",
        "juice",
        "milk",
        "soda",
        "tea",
        "water",
        "\u5496\u5561",
        "\u679c\u6c41",
        "\u6c34",
        "\u6c7d\u6c34",
        "\u725b\u5976",
        "\u8336",
        "\u996e\u6599",
    ),
    "Electronics": (
        "adapter",
        "battery",
        "cable",
        "charger",
        "electronic",
        "phone",
        "usb",
    ),
    "Fat": (
        "avocado",
        "butter",
        "nut",
        "oil",
    ),
    "Instant": (
        "instant",
        "ramen",
        "\u65b9\u4fbf\u9762",
        "\u62c9\u9762",
        "\u901f\u98df",
    ),
    "Protein": (
        "beef",
        "chicken",
        "drumstick",
        "egg",
        "fish",
        "meat",
        "pork",
        "sausage",
        "shrimp",
        "tofu",
        "tuna",
        "\u725b",
        "\u732a",
        "\u8089",
        "\u867e",
        "\u86cb",
        "\u9c7c",
        "\u9e21",
    ),
    "Sauce": (
        "dressing",
        "ketchup",
        "salsa",
        "sauce",
        "seasoning",
        "soy",
        "spice",
        "vinegar",
        "\u6599\u9152",
        "\u751f\u62bd",
        "\u8001\u62bd",
        "\u868c\u6cb9",
        "\u8c03\u5473",
        "\u9171",
        "\u918b",
    ),
    "Snacks": (
        "bar",
        "candy",
        "chips",
        "chocolate",
        "cookie",
        "cracker",
        "popcorn",
        "snack",
        "\u7cd5",
        "\u85af\u7247",
        "\u997c\u5e72",
        "\u96f6\u98df",
    ),
    "Study": (
        "book",
        "notebook",
        "paper",
        "pen",
        "pencil",
        "school",
        "study",
    ),
    "Vegetables": (
        "broccoli",
        "carrot",
        "cucumber",
        "lettuce",
        "onion",
        "pepper",
        "spinach",
        "tomato",
        "vegetable",
        "\u59dc",
        "\u756a\u8304",
        "\u83dc",
        "\u8471",
        "\u849c",
        "\u897f\u5170\u82b1",
        "\u9ec4\u74dc",
    ),
}

CATEGORY_ALIASES = {
    "Carbonhydrate": ("carbonhydrate", "carbohydrate", "carbs", "\u78b3\u6c34", "\u4e3b\u98df", "\u6dc0\u7c89"),
    "Daily Necessities": ("daily necessities", "daily necessity", "\u65e5\u7528\u54c1"),
    "Drinks": ("drinks", "drink", "beverages", "beverage", "\u996e\u6599"),
    "Electronics": ("electronics", "electronic", "\u7535\u5b50"),
    "Fat": ("fat", "fats", "\u8102\u80aa"),
    "Instant": ("instant", "\u901f\u98df"),
    "Protein": ("protein", "proteins", "\u86cb\u767d\u8d28"),
    "Sauce": ("sauce", "sauces", "condiment", "condiments", "\u8c03\u6599", "\u9171\u6599", "\u914d\u6599"),
    "Snacks": ("snacks", "snack", "\u96f6\u98df"),
    "Study": ("study", "\u5b66\u4e60"),
    "Vegetables": ("vegetables", "vegetable", "produce", "fruit", "fruits", "\u852c\u83dc", "\u6c34\u679c"),
}

SEMANTIC_CATEGORY_KEYWORDS = {
    "Protein": (
        "bacon",
        "beef",
        "cheese",
        "chicken",
        "drumstick",
        "egg",
        "eggs",
        "fish",
        "ham",
        "meat",
        "milk",
        "pork",
        "protein",
        "salmon",
        "sausage",
        "shrimp",
        "steak",
        "tofu",
        "tuna",
        "turkey",
        "yogurt",
        "\u4e09\u6587\u9c7c",
        "\u4e73",
        "\u54b8\u86cb",
        "\u54b8\u9e2d\u86cb",
        "\u5976\u916a",
        "\u725b\u5976",
        "\u725b\u8089",
        "\u732a\u8089",
        "\u706b\u817f",
        "\u70e4\u9e2d",
        "\u8089",
        "\u817f",
        "\u86cb",
        "\u86cb\u767d",
        "\u867e",
        "\u8c46\u5e72",
        "\u8c46\u8150",
        "\u9178\u5976",
        "\u9c7c",
        "\u9e21",
        "\u9e2d",
        "\u9e45",
        "\u9ec4\u6cb9",
        "\u829d\u58eb",
    ),
    "Vegetables": (
        "apple",
        "asparagus",
        "avocado",
        "banana",
        "berry",
        "blueberry",
        "broccoli",
        "cabbage",
        "carrot",
        "celery",
        "cucumber",
        "fruit",
        "grape",
        "greens",
        "lettuce",
        "mango",
        "melon",
        "mushroom",
        "onion",
        "orange",
        "peach",
        "pear",
        "pepper",
        "pineapple",
        "potato",
        "spinach",
        "strawberry",
        "tomato",
        "vegetable",
        "\u571f\u8c46",
        "\u5723\u5973\u679c",
        "\u6c34\u679c",
        "\u6d0b\u8471",
        "\u7247\u82b1",
        "\u751f\u83dc",
        "\u756a\u8304",
        "\u767d\u83dc",
        "\u7af9\u7b0b",
        "\u80e1\u841d\u535c",
        "\u82a5\u83dc",
        "\u82b9\u83dc",
        "\u82f9\u679c",
        "\u8349\u8393",
        "\u83c7",
        "\u83dc",
        "\u83e0\u83dc",
        "\u841d\u535c",
        "\u8461\u8404",
        "\u84dd\u8393",
        "\u852c",
        "\u852c\u83dc",
        "\u8584\u8377",
        "\u858f",
        "\u897f\u5170\u82b1",
        "\u897f\u74dc",
        "\u9999\u83dc",
        "\u9999\u8549",
        "\u9ec4\u74dc",
    ),
    "Sauce": (
        "broth",
        "condiment",
        "cooking wine",
        "dressing",
        "ketchup",
        "marinade",
        "mayonnaise",
        "oyster sauce",
        "chili",
        "chilli",
        "chile",
        "jalapeno",
        "pepper",
        "peppercorn",
        "salt",
        "salsa",
        "sauce",
        "seasoning",
        "soy sauce",
        "spice",
        "sugar",
        "vinegar",
        "\u4e94\u9999",
        "\u516b\u89d2",
        "\u5265\u76ae\u849c",
        "\u59dc",
        "\u5c0f\u7c73\u6912",
        "\u5c16\u6912",
        "\u5e72\u8fa3\u6912",
        "\u5e72\u6912",
        "\u6842\u76ae",
        "\u6ce1\u6912",
        "\u6599\u7406\u9152",
        "\u6599\u9152",
        "\u6c64\u6599",
        "\u6c99\u62c9\u9171",
        "\u6cb9",
        "\u6d77\u9c9c\u9171",
        "\u706b\u9505\u5e95\u6599",
        "\u738b\u81f4\u548c",
        "\u751f\u62bd",
        "\u756a\u8304\u9171",
        "\u76d0",
        "\u80e1\u6912",
        "\u8001\u5e72\u5988",
        "\u8001\u62bd",
        "\u868c\u6cb9",
        "\u82b1\u6912",
        "\u8c03\u5473",
        "\u8c03\u6599",
        "\u674e\u9526\u8bb0",
        "\u8c46\u74e3",
        "\u8c46\u6c99",
        "\u8fa3\u6912",
        "\u8fa3\u6912\u6cb9",
        "\u914d\u6599",
        "\u9171",
        "\u9171\u6599",
        "\u9171\u6cb9",
        "\u918b",
        "\u8471",
        "\u849c",
        "\u8611\u83c7\u9171",
        "\u867e\u76ae",
        "\u869d\u6cb9",
        "\u9752\u6912",
        "\u97ed\u83dc\u82b1",
        "\u9999\u53f6",
        "\u9999\u6599",
        "\u9ebb\u6912",
        "\u9ebb\u8fa3",
        "\u6912",
    ),
    "Carbonhydrate": (
        "bagel",
        "bao",
        "bread",
        "bun",
        "carb",
        "cereal",
        "corn",
        "dumpling",
        "flour",
        "glutinous rice",
        "macaroni",
        "noodle",
        "oat",
        "pasta",
        "ramen",
        "rice",
        "spaghetti",
        "starch",
        "tortilla",
        "\u4e3b\u98df",
        "\u51c9\u76ae",
        "\u5305\u5b50",
        "\u571f\u8c46\u6dc0\u7c89",
        "\u5927\u7c73",
        "\u5e74\u7cd5",
        "\u62c9\u9762",
        "\u6302\u9762",
        "\u65b9\u4fbf\u9762",
        "\u6cb3\u7c89",
        "\u6dc0\u7c89",
        "\u7c73",
        "\u7c73\u7c89",
        "\u7c73\u996d",
        "\u7c89",
        "\u7c89\u4e1d",
        "\u7cef\u7c73",
        "\u7ea2\u85af",
        "\u85af",
        "\u858f",
        "\u9762",
        "\u9762\u5305",
        "\u9762\u6761",
        "\u9762\u7c89",
        "\u997a\u5b50",
        "\u997c",
        "\u9a6c\u94c3\u85af",
        "\u9ea6",
        "\u9ea6\u7247",
    ),
    "Daily Necessities": (
        "body wash",
        "butcher twine",
        "cleaner",
        "conditioner",
        "cotton twine",
        "detergent",
        "dish soap",
        "food safe string",
        "garbage bag",
        "hand soap",
        "kitchen twine",
        "laundry",
        "mask",
        "napkin",
        "paper towel",
        "shampoo",
        "soap",
        "sponge",
        "tissue",
        "toilet paper",
        "toothbrush",
        "toothpaste",
        "towel",
        "trash bag",
        "twine",
        "\u4fdd\u9c9c\u819c",
        "\u536b\u751f\u5dfe",
        "\u536b\u751f\u7eb8",
        "\u53a8\u623f\u7eb8",
        "\u5783\u573e\u888b",
        "\u62a4\u53d1\u7d20",
        "\u62a4\u80a4",
        "\u62bd\u7eb8",
        "\u6c90\u6d74",
        "\u6c90\u6d74\u9732",
        "\u6d17\u53d1",
        "\u6d17\u53d1\u6c34",
        "\u6d17\u624b\u6db2",
        "\u6d17\u6d01\u7cbe",
        "\u6d17\u8863",
        "\u6d17\u8863\u6db2",
        "\u6d17\u9762\u5976",
        "\u6e05\u6d01",
        "\u7259\u5237",
        "\u7259\u7ebf",
        "\u7259\u818f",
        "\u7eb8\u5dfe",
        "\u9762\u819c",
        "\u9999\u7682",
    ),
    "Drinks": (
        "coffee",
        "cola",
        "coke",
        "drink",
        "soda",
        "tea",
        "water",
        "\u5496\u5561",
        "\u6c34",
        "\u6c7d\u6c34",
        "\u78b3\u9178\u996e\u6599",
        "\u8336",
        "\u996e\u6599",
    ),
    "Snacks": (
        "candy",
        "cake",
        "chips",
        "chocolate",
        "cookie",
        "cracker",
        "pastry",
        "popcorn",
        "snack",
        "\u86cb\u7cd5",
        "\u5de7\u514b\u529b",
        "\u679c\u51bb",
        "\u7cd5",
        "\u7cd5\u70b9",
        "\u85af\u7247",
        "\u997c\u5e72",
        "\u96f6\u98df",
    ),
}

CONTEXT_EXCLUSIONS = {
    "Protein": (
        "butcher twine",
        "cotton butcher",
        "craft baker",
        "crocheting",
        "food safe string",
        "gardening",
        "knitting",
        "twine",
        "wrapping",
        "\u86cb\u7cd5",
        "\u7cd5\u70b9",
        "\u6d17\u9762\u5976",
        "\u9762\u819c",
        "\u62a4\u80a4",
        "\u6d17\u53d1",
    ),
    "Carbonhydrate": ("\u9762\u819c", "\u6d17\u9762\u5976"),
    "Vegetables": (
        "chili",
        "chile",
        "jalapeno",
        "\u516b\u89d2",
        "\u59dc",
        "\u5c16\u6912",
        "\u5e72\u8fa3\u6912",
        "\u6842\u76ae",
        "\u6ce1\u6912",
        "\u80e1\u6912",
        "\u82b1\u6912",
        "\u8fa3\u6912",
        "\u8471",
        "\u849c",
        "\u9752\u6912",
        "\u9999\u53f6",
        "\u9ebb\u6912",
        "\u6912",
    ),
}

UNIT_PRICE_LABEL = r"(?:unit\s*price|price\s*each|each|price|\u5355\s*\u4ef7|\u55ae\s*\u50f9|\u5355\s*[1ilI]?\s*[\u98e0\u98df])"
QUANTITY_LABEL = r"(?:quantity|qty|\u6570\s*\u91cf|\u6578\s*\u91cf|\u91cc|\u91cf)"
MONEY_TOKEN = r"[$\u00a5\uffe5]?\s*[0-9gGoOlI&]{1,5}(?:\s*[,.\uff0e\u00b7]\s*[0-9gGoOlI&]{1,2}|(?:\s+[0-9gGoOlI&]){1,3})?"
SPACED_CENTS_MONEY_TOKEN = r"[$\u00a5\uffe5]?\s*[0-9gGoOlI&]{1,2}\s+[0-9gGoOlI&]{2}"
QTY_TOKEN = r"[0-9]{1,4}(?:\s*[,.\uff0e]\s*[0-9]+)?"
ORDER_LINE_RE = re.compile(
    rf"(?P<item>.{{0,180}}?){UNIT_PRICE_LABEL}\s*[:\uff1a]?\s*(?P<unit>{MONEY_TOKEN})"
    rf"(?:\s*[|,，;；\-\]\[()（）【】]\s*|\s+)*{QUANTITY_LABEL}\s*[:\uff1a]?\s*(?P<qty>{QTY_TOKEN})",
    re.IGNORECASE | re.DOTALL,
)
ORDER_LINE_DEFAULT_QTY_RE = re.compile(
    rf"(?P<item>.{{0,180}}?){UNIT_PRICE_LABEL}\s*[:\uff1a]?\s*(?P<unit>{MONEY_TOKEN})"
    rf"(?:\s*[|,，;；\-\]\[()（）【】]\s*|\s+)*(?:{QUANTITY_LABEL})?(?=\s*[$\u00a5\uffe5]|\s*$)",
    re.IGNORECASE | re.DOTALL,
)
ORDER_LINE_LOOSE_RE = re.compile(
    rf"(?P<item>.{{0,140}}?){UNIT_PRICE_LABEL}\s*[:\uff1a]?\s*(?P<unit>{MONEY_TOKEN})"
    rf"(?:\s*[|,，;；\-\]\[()（）【】]\s*|\s+)+(?![$\u00a5\uffe5])(?P<qty>[0-9]{{1,3}})(?=\s|$)",
    re.IGNORECASE | re.DOTALL,
)


ORDER_LINE_SEPARATOR = r"(?:\s*[|\u4e28;:()\[\]\{\}\-_/\\\u3000-\u303f\uff1a\uff1b\uff08\uff09\uff3b\uff3d]\s*|\s+)"
ORDER_LINE_SPACED_CENTS_RE = re.compile(
    rf"(?P<item>.{{0,180}}?){UNIT_PRICE_LABEL}\s*[:\uff1a]?\s*(?P<unit>{SPACED_CENTS_MONEY_TOKEN})"
    rf"(?:\s+[1Il])?{ORDER_LINE_SEPARATOR}*{QUANTITY_LABEL}\s*[:,.\uff0c\uff0e\uff1a]?\s*(?P<qty>{QTY_TOKEN})",
    re.IGNORECASE | re.DOTALL,
)
ORDER_LINE_RE = re.compile(
    rf"(?P<item>.{{0,180}}?){UNIT_PRICE_LABEL}\s*[:\uff1a]?\s*(?P<unit>{MONEY_TOKEN})"
    rf"{ORDER_LINE_SEPARATOR}*{QUANTITY_LABEL}\s*[:,.\uff0c\uff0e\uff1a]?\s*(?P<qty>{QTY_TOKEN})",
    re.IGNORECASE | re.DOTALL,
)
ORDER_LINE_DEFAULT_QTY_RE = re.compile(
    rf"(?P<item>.{{0,180}}?){UNIT_PRICE_LABEL}\s*[:\uff1a]?\s*(?P<unit>{MONEY_TOKEN})"
    rf"{ORDER_LINE_SEPARATOR}*(?:{QUANTITY_LABEL})?(?=\s*[$\u00a5\uffe5]|\s*$)",
    re.IGNORECASE | re.DOTALL,
)
ORDER_LINE_LOOSE_RE = re.compile(
    rf"(?P<item>.{{0,140}}?){UNIT_PRICE_LABEL}\s*[:\uff1a]?\s*(?P<unit>{MONEY_TOKEN})"
    rf"{ORDER_LINE_SEPARATOR}+(?![$\u00a5\uffe5])(?P<qty>[0-9]{{1,3}})(?=\s|$)",
    re.IGNORECASE | re.DOTALL,
)
MARKETPLACE_PRICE_TOKEN = (
    r"(?<![A-Za-z0-9])(?:"
    r"(?:[$\u00a5\uffe5]\s*)?[0-9sSgGoOlI&]{1,4}\s*[.\uff0e\u00b7]\s*[0-9sSgGoOlI&]{1,2}"
    r"|[sS]\s*[sS0-9]\s*[.\uff0e\u00b7]\s*[gG9]{1,2}"
    r"|[$\u00a5\uffe5]\s*[0-9sSgGoOlI&]{1,4}"
    r")(?![A-Za-z0-9])"
)
MARKETPLACE_PRICE_RE = re.compile(MARKETPLACE_PRICE_TOKEN, re.IGNORECASE)
MARKETPLACE_ITEM_RE = re.compile(
    rf"(?P<item>.{{8,260}}?)\s+Sold\s+by:?\s+.{1,180}?"
    rf"(?P<price>{MARKETPLACE_PRICE_TOKEN})(?=\s*(?:[©@]\s*)?(?:Buy\s+it\s+again|View\s+your\s+item|$))",
    re.IGNORECASE | re.DOTALL,
)
MARKETPLACE_SELLER_RE = re.compile(
    r"\b(?:(?:Sold\s+by|Ships\s+from|Fulfilled\s+by)\s*:?\s+|(?:Seller|Merchant|Vendor)\s*:\s+)",
    re.IGNORECASE,
)
MARKETPLACE_ACTION_RE = re.compile(
    r"\b(?:"
    r"Buy\s+it\s+again|View\s+your\s+item|Add\s+to\s+cart|Add\s+to\s+bag|Go\s+to\s+cart|"
    r"Return\s+or\s+replace\s+items|Track\s+package|Leave\s+seller\s+feedback|"
    r"Write\s+a\s+product\s+review|Share\s+gift\s+receipt"
    r")\b",
    re.IGNORECASE,
)
MARKETPLACE_CONTROL_MARKERS = (
    "add to bag",
    "add to cart",
    "add to list",
    "buy it again",
    "delivered today",
    "for free delivery",
    "get product support",
    "go to cart",
    "leave seller feedback",
    "order details",
    "return or replace items",
    "share gift receipt",
    "suggested",
    "track package",
    "view your item",
    "write a product review",
    "your package was delivered",
)


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def normalize_ocr_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    replacements = {
        "\u55ae": "\u5355",
        "\u50f9": "\u4ef7",
        "\u6578": "\u6570",
        "\uff1a": ":",
        "\uff0e": ".",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\u5355\s*[1ilI]?\s*[\u98e0\u98df]", "\u5355\u4ef7", text)
    text = re.sub(r"([$\u00a5\uffe5]\s*[0-9gGoOlI&](?:\s*[0-9gGoOlI&]){0,3})\s+g\b", r"\1 9", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip(" -:\t")
    line = re.sub(r"[$\u00a5]?\s*[0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]{1,2})$", "", line).strip(" -:\t")
    return line


def parse_order_text(text: str, reference: ReferenceData | None = None, today: date | None = None) -> OrderCandidate:
    reference = reference or ReferenceData()
    today = today or date.today()
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    purchase_date = extract_purchase_date(lines, today=today)
    order_lines = extract_order_lines(lines, reference)
    if not order_lines:
        order_lines = extract_marketplace_lines(lines, reference)
    if order_lines:
        price = round(sum(line.price or 0 for line in order_lines), 2)
        item = order_lines[0].item if len(order_lines) == 1 else None
        category = order_lines[0].category if len(order_lines) == 1 else None
        category_score = 0.85
    else:
        price = extract_price(lines)
        item = extract_item(lines, reference)
        category, category_score = choose_category(item, reference)

    notes: list[str] = []
    score = 0.0
    if order_lines:
        score += min(0.45, 0.25 + 0.04 * len(order_lines))
    elif item:
        score += 0.35
    else:
        notes.append("No item line was confidently detected.")
    if purchase_date:
        score += 0.25
    else:
        notes.append("No purchase date was detected.")
    if price is not None:
        score += 0.25
    else:
        notes.append("No price was detected.")
    if category:
        score += 0.15 * max(category_score, 0.3)
    elif order_lines:
        score += 0.08
    else:
        notes.append("No category was detected.")

    return OrderCandidate(
        item=item,
        purchase_date=purchase_date,
        price=price,
        category=category,
        lines=order_lines,
        raw_text=text,
        confidence=round(min(score, 1.0), 2),
        notes=notes,
    )


def extract_order_lines(lines: Iterable[str], reference: ReferenceData) -> list[OrderLine]:
    text = normalize_ocr_text(" ".join(lines))
    results: list[OrderLine] = []

    strict_matches = list(ORDER_LINE_RE.finditer(text))
    strict_spans = [match.span() for match in strict_matches]
    loose_matches = [
        match
        for match in ORDER_LINE_LOOSE_RE.finditer(text)
        if not any(_spans_overlap(match.span(), span) for span in strict_spans)
    ]
    spaced_cents_matches = []
    default_qty_matches = []
    search_start = 0
    for existing_match in sorted(strict_matches + loose_matches, key=lambda match: match.start()):
        if existing_match.start() > search_start:
            spaced_cents_matches.extend(
                ORDER_LINE_SPACED_CENTS_RE.finditer(text, search_start, existing_match.start())
            )
            default_qty_matches.extend(ORDER_LINE_DEFAULT_QTY_RE.finditer(text, search_start, existing_match.start()))
        search_start = max(search_start, existing_match.end())
    if search_start < len(text):
        spaced_cents_matches.extend(ORDER_LINE_SPACED_CENTS_RE.finditer(text, search_start))
        default_qty_matches.extend(ORDER_LINE_DEFAULT_QTY_RE.finditer(text, search_start))
    matches = sorted(strict_matches + loose_matches + spaced_cents_matches + default_qty_matches, key=lambda match: match.start())
    for match in matches:
        item = _clean_order_item(match.group("item"))
        unit_price = parse_money_token(match.group("unit"))
        qty_text = match.groupdict().get("qty")
        quantity = parse_quantity_token(qty_text) if qty_text else 1
        unit_price = _repair_ocr_unit_price(item, match.group("unit"), unit_price)
        if not item or unit_price is None or quantity is None:
            continue
        if quantity <= 0 or unit_price <= 0:
            continue
        if _is_noise_line(item) or _looks_like_price_noise(item):
            continue

        category, category_score = choose_category(item, reference)
        confidence = 0.72 + min(0.18, len(item) / 120)
        if category:
            confidence += min(0.1, category_score * 0.1)
        results.append(
            OrderLine(
                item=item,
                unit_price=unit_price,
                quantity=quantity,
                category=category,
                confidence=round(min(confidence, 1.0), 2),
            )
        )

    return _dedupe_order_lines(results)


def extract_marketplace_lines(lines: Iterable[str], reference: ReferenceData) -> list[OrderLine]:
    text = normalize_ocr_text(" ".join(lines))
    results: list[OrderLine] = []
    sold_by_matches = list(MARKETPLACE_SELLER_RE.finditer(text))
    previous_end = 0

    for index, sold_match in enumerate(sold_by_matches):
        next_sold_start = sold_by_matches[index + 1].start() if index + 1 < len(sold_by_matches) else len(text)
        item = _clean_marketplace_item(text[previous_end : sold_match.start()])
        tail = text[sold_match.end() : next_sold_start]
        price_match = MARKETPLACE_PRICE_RE.search(tail)
        if not price_match:
            continue
        unit_price = _parse_marketplace_price_token(price_match.group(0))
        if not item or unit_price is None or unit_price <= 0:
            continue
        if _is_noise_line(item) or _looks_like_price_noise(item):
            continue

        category, category_score = choose_category(item, reference)
        confidence = 0.68 + min(0.18, len(item) / 160)
        if category:
            confidence += min(0.1, category_score * 0.1)
        results.append(
            OrderLine(
                item=item,
                unit_price=unit_price,
                quantity=1,
                category=category,
                confidence=round(min(confidence, 1.0), 2),
            )
        )
        after_price = sold_match.end() + price_match.end()
        action_match = MARKETPLACE_ACTION_RE.search(text[after_price:next_sold_start])
        previous_end = after_price + (action_match.end() if action_match else 0)

    return _dedupe_order_lines(results)


def parse_money_token(value: str) -> float | None:
    normalized = unicodedata.normalize("NFKC", value)
    has_currency = bool(re.search(r"[$\u00a5\uffe5]", normalized))
    has_decimal = bool(re.search(r"[,.\uff0e\u00b7]", normalized))
    compact = re.sub(r"\s+", "", normalized)
    compact = compact.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "G": "9", "g": "9", "&": "6"}))
    compact = compact.replace(",", ".").replace("\u00b7", ".")
    compact = re.sub(r"[^0-9.]", "", compact)
    if not compact:
        return None
    if compact.count(".") > 1:
        pieces = compact.split(".")
        compact = "".join(pieces[:-1]) + "." + pieces[-1]
    if has_currency and not has_decimal and compact.isdigit() and len(compact) in {3, 4}:
        compact = f"{compact[:-2]}.{compact[-2:]}"
    try:
        return round(float(compact), 2)
    except ValueError:
        return None


def _parse_marketplace_price_token(value: str) -> float | None:
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
    has_currency = bool(re.search(r"[$\u00a5\uffe5]", compact))
    if not has_currency and re.match(r"^[sS][sS0-9]", compact):
        compact = "$" + compact[1:]
    if re.fullmatch(r"[$\u00a5\uffe5]?[sS5]\s*[.\uff0e\u00b7]\s*[gG9]", compact):
        compact = re.sub(r"([.\uff0e\u00b7])\s*[gG9]$", r"\g<1>99", compact)
    compact = compact.translate(str.maketrans({"S": "5", "s": "5"}))
    return parse_money_token(compact)


def parse_quantity_token(value: str) -> float | None:
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
    compact = compact.replace(",", ".")
    compact = re.sub(r"[^0-9.]", "", compact)
    if not compact:
        return None
    try:
        quantity = float(compact)
    except ValueError:
        return None
    return int(quantity) if quantity.is_integer() else quantity


def _clean_order_item(value: str) -> str:
    text = normalize_ocr_text(value)
    text = re.sub(
        r".*(?:OCR\s*Text|Parsed\s+OCR|Workbook|Capture\s+Screen|Open\s+Image|OCR\s+Clipboard|Parse\s+Text|OCR\s+Language)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?:^|\s)(?:Item|Purchase\s+Date|Category|Confidence|Save\s+to\s+Workbook|Clear)\b.*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^\s*(?:[|,，;；:\-_\]\[]|\d+|[一二三四五六七八九十])+\s*", "", text)
    text = _strip_browser_noise_prefix(text)
    text = re.sub(
        rf"^\s*(?:{QUANTITY_LABEL})\s*[:,.\uff0c\uff0e\uff1a]?\s*{QTY_TOKEN}\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+", " ", text).strip(" |,，;；:-_\t\r\n")
    if len(text) > 90:
        text = text[-90:].strip(" |,，;；:-_\t\r\n")
    return text


def _clean_marketplace_item(value: str) -> str:
    text = normalize_ocr_text(value)
    lowered = text.casefold()
    cut_at = -1
    for marker in MARKETPLACE_CONTROL_MARKERS:
        marker_index = lowered.rfind(marker)
        if marker_index >= 0:
            cut_at = max(cut_at, marker_index + len(marker))
    if cut_at >= 0:
        text = text[cut_at:]

    text = re.sub(
        r"\b(?:Get\s+product\s+support|Track\s+package|Return\s+or\s+replace\s+items|Share\s+gift\s+receipt|Leave\s+seller\s+feedback|Write\s+a\s+product\s+review|Buy\s+it\s+again|View\s+your\s+item|Add\s+to\s+cart|Add\s+to\s+bag|Go\s+to\s+cart)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bDelivered\s+today\b.*?\bresident\b\.?", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" |,.-:\t\r\n")
    text = re.sub(r"^(?:Delivered|Ordered|Purchased)\s+", "", text, flags=re.IGNORECASE)
    text = _strip_marketplace_leading_price_noise(text)
    text = _strip_marketplace_leading_noise(text)
    if len(text) > 240:
        text = text[:240].strip(" |,.-:\t\r\n")
    return text


def _strip_marketplace_leading_price_noise(text: str) -> str:
    price_matches = list(MARKETPLACE_PRICE_RE.finditer(text))
    if not price_matches:
        return text
    tail = text[price_matches[-1].end() :].strip(" |,.-:\t\r\n")
    if _looks_like_marketplace_title_start(tail):
        return tail
    return text


def _strip_marketplace_leading_noise(text: str) -> str:
    tokens = text.split()
    for index in range(1, min(5, len(tokens))):
        prefix = tokens[:index]
        tail = " ".join(tokens[index:])
        if any(_is_ocr_noise_token(token) for token in prefix) and _looks_like_marketplace_title_start(tail):
            return tail.strip(" |,.-:\t\r\n")
    return text.strip(" |,.-:\t\r\n")


def _is_ocr_noise_token(token: str) -> bool:
    cleaned = token.strip(" |,.-:\t\r\n")
    if re.fullmatch(r"\d{1,4}", cleaned):
        return True
    if 1 <= len(cleaned) <= 4 and re.search(r"[a-z].*[A-Z]", cleaned):
        return True
    return False


def _looks_like_marketplace_title_start(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 6:
        return False
    first = stripped.split(maxsplit=1)[0].strip(" |,.-:\t\r\n")
    return bool(
        re.search(r"[A-Za-z0-9\u4e00-\u9fff]", stripped)
        and (
            "&" in first
            or bool(re.fullmatch(r"[A-Z0-9][A-Z0-9-]{3,}", first))
            or bool(re.match(r"[A-Z][a-z]+(?:\s+[A-Z][A-Za-z0-9]+)", stripped))
            or bool(re.search(r"[\u4e00-\u9fff]", stripped[:12]))
        )
    )


def _strip_browser_noise_prefix(text: str) -> str:
    lowered = text.casefold()
    cut_at = -1
    for marker in BROWSER_NOISE_MARKERS:
        marker_index = lowered.rfind(marker)
        if marker_index >= 0:
            cut_at = max(cut_at, marker_index + len(marker))

    if cut_at >= 0 and re.search(r"[\u4e00-\u9fff]", text[cut_at:]):
        text = text[cut_at:]

    return re.sub(r"^(?:[^A-Za-z\u4e00-\u9fff]+|[A-Za-z]\s*){1,12}(?=[\u4e00-\u9fff])", "", text)


def _repair_ocr_unit_price(item: str, token: str, unit_price: float | None) -> float | None:
    if unit_price is None:
        return None

    compact_item = normalize_ocr_text(item).casefold().replace(" ", "")
    normalized_token = unicodedata.normalize("NFKC", token)
    compact_token = re.sub(
        r"[^0-9]",
        "",
        normalized_token.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})),
    )
    looks_like_large_rice = (
        unit_price < 2
        and compact_token.startswith("1")
        and len(compact_token) == 3
        and any(word in compact_item for word in ("\u7cef\u7c73", "\u5927\u7c73", "\u7c73", "rice"))
        and re.search(r"(?:5|五)\s*(?:\u78c5|lb|lbs|pound)", normalize_ocr_text(item), flags=re.IGNORECASE)
    )
    if looks_like_large_rice:
        return round(float(f"10.{compact_token[-2:]}"), 2)

    return unit_price


def _dedupe_order_lines(lines: list[OrderLine]) -> list[OrderLine]:
    seen: set[tuple[str, float | None, float]] = set()
    unique: list[OrderLine] = []
    for line in lines:
        key = (normalize_key(line.item), line.unit_price, line.quantity)
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return unique


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def extract_purchase_date(lines: Iterable[str], today: date | None = None) -> date | None:
    today = today or date.today()
    line_list = list(lines)
    labelled = [line for line in line_list if any(label in line.casefold() for label in DATE_LABELS)]

    for line in labelled + line_list:
        found = _date_from_line(line, today)
        if found:
            return found
    return None


def _date_from_line(line: str, today: date) -> date | None:
    line = _remove_non_purchase_date_ranges(line)
    if not line.strip():
        return None
    normalized = (
        line.replace("\u5e74", "-")
        .replace("\u6708", "-")
        .replace("\u65e5", " ")
        .replace(",", " ")
    )
    candidates: list[str] = []
    for pattern in DATE_PATTERNS:
        candidates.extend(re.findall(pattern, normalized, flags=re.IGNORECASE))

    for candidate in candidates:
        if isinstance(candidate, tuple):
            candidate = candidate[0]
        parsed = _parse_date_candidate(candidate, today)
        if parsed:
            return parsed

    if any(label in line.casefold() for label in DATE_LABELS):
        parsed = _parse_date_candidate(normalized, today)
        if parsed:
            return parsed
    return None


def _remove_non_purchase_date_ranges(line: str) -> str:
    return re.sub(
        r"\b(?:Return\s+(?:or\s+replace\s+)?items?|Eligible\s+through)\b.{0,80}?(?:\d{4}|\d{1,2},\s*\d{4})",
        " ",
        line,
        flags=re.IGNORECASE,
    )


def _parse_date_candidate(value: str, today: date) -> date | None:
    try:
        default = datetime(today.year, 1, 1)
        parsed = date_parser.parse(value, fuzzy=True, default=default)
    except (ValueError, OverflowError):
        return None

    parsed_date = parsed.date()
    if parsed_date.year < 2018:
        return None
    if parsed_date > today.replace(year=today.year + 1):
        return None
    if parsed_date > today:
        try:
            adjusted = parsed_date.replace(year=parsed_date.year - 1)
        except ValueError:
            adjusted = parsed_date
        if adjusted <= today:
            return adjusted
    return parsed_date


def extract_price(lines: Iterable[str]) -> float | None:
    line_list = list(lines)
    labelled_prices: list[tuple[int, float]] = []
    all_prices: list[float] = []

    for line in line_list:
        prices = _prices_in_line(line)
        if not prices:
            continue
        all_prices.extend(prices)
        lowered = line.casefold()
        for index, label in enumerate(PRICE_PRIORITY):
            if label in lowered:
                labelled_prices.append((index, prices[-1]))
                break

    if labelled_prices:
        labelled_prices.sort(key=lambda pair: pair[0])
        return labelled_prices[0][1]
    if all_prices:
        reasonable = [value for value in all_prices if 0 < value < 10000]
        if reasonable:
            return max(reasonable)
    return None


def _prices_in_line(line: str) -> list[float]:
    values: list[float] = []
    for match in PRICE_RE.finditer(line):
        token = match.group(1).replace(",", "")
        try:
            values.append(round(float(token), 2))
        except ValueError:
            continue
    return values


def extract_item(lines: Iterable[str], reference: ReferenceData) -> str | None:
    candidates: list[tuple[float, str]] = []

    for line in lines:
        cleaned = clean_line(line)
        if not cleaned or _is_noise_line(cleaned):
            continue
        if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", cleaned):
            continue
        score = min(len(cleaned), 80) / 80
        fuzzy_item, fuzzy_score = best_reference_item(cleaned, reference)
        if fuzzy_item and fuzzy_score >= 0.78:
            return fuzzy_item
        score += fuzzy_score
        if any(word in cleaned.casefold() for word in ("item", "product", "description")):
            score += 0.2
        candidates.append((score, cleaned))

    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def _is_noise_line(line: str) -> bool:
    lowered = line.casefold()
    if any(word in lowered for word in NOISE_WORDS):
        return True
    if any(word in line for word in CN_NOISE_WORDS):
        return True
    if re.fullmatch(r"[$\u00a5]?\s*[0-9,.]+", line):
        return True
    return False


def _looks_like_price_noise(item: str) -> bool:
    text = normalize_ocr_text(item)
    lowered = text.casefold()
    if lowered.startswith("row") and ("\u5355\u4ef7" in text or "$" in text):
        return True
    if text.count("$") + text.count("\u00a5") + text.count("\uffe5") >= 2:
        return True
    letters = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", text))
    digits = len(re.findall(r"\d", text))
    if letters == 0 and digits > 0:
        return True
    if letters <= 1 and digits >= 4:
        return True
    if re.fullmatch(r"[\d\s$.,\u00a5\uffe5\u00b7:：|,，;；\-_\]\[()（）【】]+", text):
        return True
    return False


def best_reference_item(value: str, reference: ReferenceData) -> tuple[str | None, float]:
    normalized = normalize_key(value)
    best_name = None
    best_score = 0.0
    for item in reference.item_category:
        score = SequenceMatcher(None, normalized, normalize_key(item)).ratio()
        if normalize_key(item) in normalized or normalized in normalize_key(item):
            score = max(score, 0.88)
        if score > best_score:
            best_name = item
            best_score = score
    return best_name, best_score


def choose_category(item: str | None, reference: ReferenceData) -> tuple[str | None, float]:
    if not item:
        return None, 0.0

    semantic_category, semantic_score = semantic_category_match(item, reference)
    if semantic_category:
        return semantic_category, semantic_score

    lowered = item.casefold()
    for category, keywords in KEYWORDS_BY_CATEGORY.items():
        for keyword in keywords:
            if keyword in lowered:
                return category, 0.75

    return None, 0.0


def semantic_category_match(item: str, reference: ReferenceData) -> tuple[str | None, float]:
    lowered = normalize_ocr_text(item).casefold()
    compact = re.sub(r"\s+", "", lowered)
    scores: dict[str, float] = {}

    for canonical_category, keywords in SEMANTIC_CATEGORY_KEYWORDS.items():
        exclusions = CONTEXT_EXCLUSIONS.get(canonical_category, ())
        if any(normalize_ocr_text(exclusion).casefold().replace(" ", "") in compact for exclusion in exclusions):
            continue
        for keyword in keywords:
            if _keyword_in_item(keyword, lowered, compact):
                scores[canonical_category] = scores.get(canonical_category, 0.0) + _keyword_weight(keyword)

    if not scores:
        return None, 0.0

    category, score = max(scores.items(), key=lambda pair: pair[1])
    confidence = min(0.98, 0.55 + score / 12)
    return category, round(confidence, 2)


def _resolve_reference_category(reference: ReferenceData, canonical_category: str) -> str | None:
    available = reference.normalized_categories
    aliases = (canonical_category, *CATEGORY_ALIASES.get(canonical_category, ()))
    for alias in aliases:
        resolved = available.get(normalize_key(alias))
        if resolved:
            return resolved
    return None


def _keyword_in_item(keyword: str, lowered_item: str, compact_item: str) -> bool:
    normalized_keyword = normalize_ocr_text(keyword).casefold()
    compact_keyword = normalized_keyword.replace(" ", "")
    if re.search(r"[\u4e00-\u9fff]", compact_keyword):
        return compact_keyword in compact_item
    return bool(re.search(rf"(?<![a-z]){re.escape(normalized_keyword)}s?(?![a-z])", lowered_item))


def _keyword_weight(keyword: str) -> float:
    normalized_keyword = normalize_ocr_text(keyword).casefold().replace(" ", "")
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized_keyword)
    if len(cjk_chars) == 1 or len(normalized_keyword) <= 2:
        return 1.4
    if cjk_chars:
        return min(5.0, 1.8 + len(cjk_chars) * 0.55)
    return min(4.5, 1.7 + len(normalized_keyword) * 0.18)


def _first_category(reference: ReferenceData) -> str | None:
    return reference.categories[0] if reference.categories else None
