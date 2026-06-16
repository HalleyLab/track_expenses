from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_WORKBOOK = Path(r"I:\Balance.xlsx")
DEFAULT_SHEET = "Sheet1"


@dataclass(frozen=True)
class AppConfig:
    workbook_path: Path = DEFAULT_WORKBOOK
    sheet_name: str = DEFAULT_SHEET
    tesseract_languages: str = "eng+chi_sim"
