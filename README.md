# Order Screenshot Recognizer

Small Python desktop tool for reading an order screenshot, extracting:

- item name
- purchase date
- price
- category

It uses `I:\Balance.xlsx` as the default reference workbook and appends new rows to `Sheet1`.

## What It Does

- Captures the full screen or opens an existing screenshot image.
- Runs OCR through the local Tesseract command line tool, with Windows OCR as a fallback.
- Builds several Chinese-friendly OCR image variants, including enlarged, sharpened, thresholded, and browser-top-cropped candidates, then chooses the text with the strongest order signal.
- Parses likely order item, purchase date, order total, and category.
- Detects multiple item rows when OCR text includes unit price and quantity, such as `unit price $4.49 quantity 2` or Chinese `unit price / quantity` labels.
- Uses built-in smart category rules instead of old item/category history from `I:\Balance.xlsx`.
- If no purchase date is found, the GUI prompts you to enter one manually.
- Saves each detected item as its own workbook row, using `unit price * quantity` as the row price.
- Classifies common groceries with semantic rules:
  - meat, eggs, and dairy -> `Protein`
  - vegetables and fruit -> `Vegetables`
  - sauces, seasonings, and cooking ingredients -> `Sauce`
  - chili peppers, peppercorn, ginger, scallion, garlic, star anise, cinnamon, bay leaves, and similar seasoning ingredients -> `Sauce`
  - staple foods, starch, flour, rice, noodles, and glutinous rice -> `Carbonhydrate`
  - household and personal-care supplies -> `Daily Necessities`
- Writes a new row with:
  - end date as `=TODAY()`
  - duration as `=DATEDIF(Cn,En,"D")+1`
  - daily price as `=Gn/Fn`

## Requirements

Python packages:

```powershell
pip install -r requirements.txt
```

OCR engine:

- On Windows, the app first tries Tesseract and then falls back to the built-in Windows OCR API.
- The GUI has an OCR Language selector. Use `Auto` for mixed screenshots, `Chinese` for Chinese orders, and `English` for English orders.
- For Chinese order pages, prefer the app's `Capture Screen` button after opening the order page. The app hides itself before capture, which avoids OCR reading the app's own buttons and tables.
- If the OCR reads Chinese punctuation into prices or quantity labels, such as `$ 4，49` or `数量，1`, the parser normalizes it before extracting rows.
- For best recognition quality, install Tesseract OCR for Windows and make sure `tesseract.exe` is on `PATH`, or set `TESSERACT_CMD` to the executable path.

The app can still parse manually pasted text if no OCR engine is available.

## Run

GUI:

```powershell
python run_gui.py
```

CLI:

```powershell
python run_cli.py --image order.png --save
```

Parse a text file without saving:

```powershell
python run_cli.py --text ocr_text.txt
```

## Notes

- The default workbook path is `I:\Balance.xlsx`.
- Before saving, the app creates a timestamped backup next to the workbook.
- The workbook headers are detected by name, so column order can change as long as the header row remains recognizable.
