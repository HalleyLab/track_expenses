from __future__ import annotations

import threading
import time
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from dateutil import parser as date_parser
from PIL import Image

from .config import DEFAULT_SHEET, DEFAULT_WORKBOOK
from .excel_store import BalanceWorkbook
from .ocr import OCRUnavailable, capture_screen, image_from_clipboard, ocr_image
from .parser import OrderCandidate, OrderLine, ReferenceData, parse_order_text


class OrderRecognizerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Order Screenshot Recognizer")
        self.geometry("1120x760")
        self.minsize(980, 650)

        self.reference = ReferenceData()
        self.current_candidate = OrderCandidate()
        self.order_lines: list[OrderLine] = []

        self.workbook_var = tk.StringVar(value=str(DEFAULT_WORKBOOK))
        self.sheet_var = tk.StringVar(value=DEFAULT_SHEET)
        self.ocr_language_var = tk.StringVar(value="Auto")
        self.status_var = tk.StringVar(value="Ready")
        self.item_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.unit_price_var = tk.StringVar()
        self.quantity_var = tk.StringVar(value="1")
        self.price_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.confidence_var = tk.StringVar(value="-")

        self._build_ui()
        self.load_reference()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        path_frame = ttk.Frame(self, padding=(12, 12, 12, 6))
        path_frame.grid(row=0, column=0, sticky="ew")
        path_frame.columnconfigure(1, weight=1)

        ttk.Label(path_frame, text="Workbook").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(path_frame, textvariable=self.workbook_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(path_frame, text="Browse", command=self.browse_workbook).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(path_frame, text="Sheet").grid(row=0, column=3, padx=(16, 8))
        ttk.Entry(path_frame, textvariable=self.sheet_var, width=12).grid(row=0, column=4)
        ttk.Button(path_frame, text="Reload", command=self.load_reference).grid(row=0, column=5, padx=(8, 0))

        button_frame = ttk.Frame(self, padding=(12, 6))
        button_frame.grid(row=1, column=0, sticky="ew")
        ttk.Button(button_frame, text="Capture Screen", command=self.capture_and_parse).pack(side="left")
        ttk.Button(button_frame, text="Open Image", command=self.open_image).pack(side="left", padx=(8, 0))
        ttk.Button(button_frame, text="OCR Clipboard", command=self.ocr_clipboard).pack(side="left", padx=(8, 0))
        ttk.Button(button_frame, text="Parse Text", command=self.parse_text).pack(side="left", padx=(8, 0))
        ttk.Label(button_frame, text="OCR Language").pack(side="left", padx=(20, 6))
        ttk.Combobox(
            button_frame,
            textvariable=self.ocr_language_var,
            values=["Auto", "Chinese", "English", "Chinese + English"],
            state="readonly",
            width=18,
        ).pack(side="left")

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)

        text_frame = ttk.Frame(main)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(1, weight=1)
        ttk.Label(text_frame, text="OCR Text").grid(row=0, column=0, sticky="w")
        self.text_box = tk.Text(text_frame, wrap="word", undo=True)
        self.text_box.grid(row=1, column=0, sticky="nsew")
        text_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text_box.yview)
        text_scroll.grid(row=1, column=1, sticky="ns")
        self.text_box.configure(yscrollcommand=text_scroll.set)
        main.add(text_frame, weight=3)

        form_frame = ttk.Frame(main, padding=(12, 0, 0, 0))
        form_frame.columnconfigure(1, weight=1)
        form_frame.rowconfigure(9, weight=1)
        main.add(form_frame, weight=2)

        fields = [
            ("Item", self.item_var),
            ("Purchase Date", self.date_var),
            ("Unit Price", self.unit_price_var),
            ("Quantity", self.quantity_var),
            ("Total Price", self.price_var),
            ("Category", self.category_var),
            ("Confidence", self.confidence_var),
        ]
        for row, (label, var) in enumerate(fields):
            ttk.Label(form_frame, text=label).grid(row=row, column=0, sticky="w", pady=(0, 8))
            if label == "Category":
                self.category_combo = ttk.Combobox(form_frame, textvariable=var, values=[], state="normal")
                self.category_combo.grid(row=row, column=1, sticky="ew", pady=(0, 8))
            elif label == "Confidence":
                ttk.Label(form_frame, textvariable=var).grid(row=row, column=1, sticky="w", pady=(0, 8))
            else:
                ttk.Entry(form_frame, textvariable=var).grid(row=row, column=1, sticky="ew", pady=(0, 8))

        action_frame = ttk.Frame(form_frame)
        action_frame.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(action_frame, text="Update Item", command=self.update_selected_line).pack(side="left")
        ttk.Button(action_frame, text="Remove", command=self.remove_selected_line).pack(side="left", padx=(8, 0))
        ttk.Button(action_frame, text="Save All", command=self.save_candidate).pack(side="left", padx=(8, 0))
        ttk.Button(action_frame, text="Clear", command=self.clear_form).pack(side="left", padx=(8, 0))

        ttk.Label(form_frame, text="Detected Items").grid(row=8, column=0, columnspan=2, sticky="w", pady=(14, 4))
        columns = ("item", "unit_price", "quantity", "total_price", "category")
        self.items_tree = ttk.Treeview(form_frame, columns=columns, show="headings", height=10)
        headings = {
            "item": "Item",
            "unit_price": "Unit",
            "quantity": "Qty",
            "total_price": "Total",
            "category": "Category",
        }
        widths = {
            "item": 210,
            "unit_price": 60,
            "quantity": 46,
            "total_price": 64,
            "category": 118,
        }
        for column in columns:
            self.items_tree.heading(column, text=headings[column])
            self.items_tree.column(column, width=widths[column], anchor="w", stretch=(column == "item"))
        self.items_tree.grid(row=9, column=0, columnspan=2, sticky="nsew")
        self.items_tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        items_scroll = ttk.Scrollbar(form_frame, orient="vertical", command=self.items_tree.yview)
        items_scroll.grid(row=9, column=2, sticky="ns")
        self.items_tree.configure(yscrollcommand=items_scroll.set)

        note = (
            "If OCR misses the purchase date, saving will ask for it. "
            "Each detected item is saved as one workbook row."
        )
        ttk.Label(form_frame, text=note, wraplength=360).grid(row=10, column=0, columnspan=2, sticky="ew", pady=(14, 0))

        status = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken", padding=(8, 4))
        status.grid(row=3, column=0, sticky="ew")

    def browse_workbook(self) -> None:
        path = filedialog.askopenfilename(
            title="Select workbook",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")],
        )
        if path:
            self.workbook_var.set(path)
            self.load_reference()

    def load_reference(self) -> None:
        try:
            store = self._store()
            self.reference = store.load_reference()
            values = self.reference.categories
            self.category_combo.configure(values=values)
            self.set_status(f"Loaded {len(values)} categories from workbook.")
        except Exception as exc:
            self.reference = ReferenceData()
            self.category_combo.configure(values=[])
            self.set_status(f"Could not load workbook: {exc}")

    def capture_and_parse(self) -> None:
        self.set_status("Capturing screen...")
        self.withdraw()
        self.after(250, self._capture_after_hide)

    def _capture_after_hide(self) -> None:
        try:
            time.sleep(0.15)
            image = capture_screen()
        finally:
            self.deiconify()
        self._ocr_async(image)

    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Open screenshot image",
            filetypes=[
                ("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            image = Image.open(path)
        except Exception as exc:
            messagebox.showerror("Image error", str(exc))
            return
        self._ocr_async(image)

    def ocr_clipboard(self) -> None:
        image = image_from_clipboard()
        if image is None:
            messagebox.showinfo("Clipboard", "No image was found on the clipboard.")
            return
        self._ocr_async(image)

    def _ocr_async(self, image: Image.Image) -> None:
        self.set_status("Running OCR...")

        def worker() -> None:
            try:
                text = ocr_image(image, languages=self._ocr_languages())
            except OCRUnavailable as exc:
                message = str(exc)
                self.after(0, lambda message=message: self._show_ocr_error(message))
                return
            except Exception as exc:
                message = f"OCR failed: {exc}"
                self.after(0, lambda message=message: self._show_ocr_error(message))
                return
            self.after(0, lambda: self._set_text_and_parse(text))

        threading.Thread(target=worker, daemon=True).start()

    def _show_ocr_error(self, message: str) -> None:
        self.set_status("OCR unavailable.")
        messagebox.showerror("OCR unavailable", message)

    def _set_text_and_parse(self, text: str) -> None:
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert("1.0", text)
        self.parse_text()

    def parse_text(self) -> None:
        text = self.text_box.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("No text", "Paste OCR text or run OCR first.")
            return

        candidate = parse_order_text(text, self.reference)
        if candidate.needs_purchase_date:
            manual_date = self.ask_purchase_date()
            if manual_date:
                candidate.purchase_date = manual_date
        self.current_candidate = candidate
        self._candidate_to_form(candidate)
        self.set_status("Parsed OCR text.")

    def ask_purchase_date(self) -> date | None:
        value = simpledialog.askstring(
            "Purchase date missing",
            "No purchase date was found. Enter purchase date (YYYY-MM-DD):",
            parent=self,
        )
        if not value:
            return None
        try:
            return date_parser.parse(value, fuzzy=True).date()
        except Exception:
            messagebox.showerror("Invalid date", "Please enter a valid date, such as 2026-06-16.")
            return None

    def _candidate_to_form(self, candidate: OrderCandidate) -> None:
        self.date_var.set(candidate.purchase_date.isoformat() if candidate.purchase_date else "")
        self.confidence_var.set(f"{candidate.confidence:.0%}")
        self.order_lines = list(candidate.lines)
        if not self.order_lines and candidate.item:
            self.order_lines = [
                OrderLine(
                    item=candidate.item,
                    unit_price=candidate.price,
                    quantity=1,
                    price=candidate.price,
                    category=candidate.category,
                    confidence=candidate.confidence,
                )
            ]
        self._populate_items_tree()
        first = self.items_tree.get_children()
        if first:
            self.items_tree.selection_set(first[0])
            self.items_tree.focus(first[0])
            self._line_to_form(self._line_from_tree(first[0]))
        else:
            self.item_var.set("")
            self.unit_price_var.set("")
            self.quantity_var.set("1")
            self.price_var.set("")
            self.category_var.set(candidate.category or "")

    def save_candidate(self) -> None:
        try:
            self._apply_form_to_selected_line()
            purchase_date = self._current_purchase_date()
            if purchase_date is None:
                manual_date = self.ask_purchase_date()
                if not manual_date:
                    return
                purchase_date = manual_date
                self.date_var.set(manual_date.isoformat())

            lines = self._lines_from_tree()
            if not lines:
                lines = [self._line_from_form()]

            store = self._store()
            rows: list[int] = []
            backup_path = None
            for index, line in enumerate(lines):
                candidate = OrderCandidate(
                    item=line.item,
                    purchase_date=purchase_date,
                    price=line.price,
                    category=line.category,
                    raw_text=self.text_box.get("1.0", tk.END).strip(),
                )
                result = store.append_order(candidate, backup=(index == 0))
                rows.append(result.row)
                backup_path = backup_path or result.backup_path
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return

        self.set_status(f"Saved {len(rows)} items. Backup: {backup_path}")
        messagebox.showinfo("Saved", f"Saved {len(rows)} item rows to workbook.")

    def _line_from_form(self) -> OrderLine:
        item = self.item_var.get().strip()
        category = self.category_var.get().strip()
        unit_text = self.unit_price_var.get().strip()
        quantity_text = self.quantity_var.get().strip()
        price_text = self.price_var.get().strip()

        unit_price = float(unit_text) if unit_text else None
        quantity = float(quantity_text) if quantity_text else 1
        if quantity.is_integer():
            quantity = int(quantity)
        price = float(price_text) if price_text else (round(unit_price * quantity, 2) if unit_price is not None else None)
        return OrderLine(
            item=item,
            unit_price=unit_price,
            quantity=quantity,
            price=price,
            category=category or None,
        )

    def _current_purchase_date(self) -> date | None:
        date_text = self.date_var.get().strip()
        return date_parser.parse(date_text, fuzzy=True).date() if date_text else None

    def _populate_items_tree(self) -> None:
        for item_id in self.items_tree.get_children():
            self.items_tree.delete(item_id)
        for line in self.order_lines:
            self.items_tree.insert("", tk.END, values=self._line_values(line))

    def _line_values(self, line: OrderLine) -> tuple[str, str, str, str, str]:
        return (
            line.item,
            "" if line.unit_price is None else f"{line.unit_price:.2f}",
            _format_quantity(line.quantity),
            "" if line.price is None else f"{line.price:.2f}",
            line.category or "",
        )

    def _line_from_tree(self, item_id: str) -> OrderLine:
        values = self.items_tree.item(item_id, "values")
        item, unit_price, quantity, total_price, category = values
        unit = float(unit_price) if unit_price else None
        qty = float(quantity) if quantity else 1
        if qty.is_integer():
            qty = int(qty)
        total = float(total_price) if total_price else None
        return OrderLine(item=item, unit_price=unit, quantity=qty, price=total, category=category or None)

    def _lines_from_tree(self) -> list[OrderLine]:
        return [self._line_from_tree(item_id) for item_id in self.items_tree.get_children()]

    def _line_to_form(self, line: OrderLine) -> None:
        self.item_var.set(line.item)
        self.unit_price_var.set("" if line.unit_price is None else f"{line.unit_price:.2f}")
        self.quantity_var.set(_format_quantity(line.quantity))
        self.price_var.set("" if line.price is None else f"{line.price:.2f}")
        self.category_var.set(line.category or "")

    def on_tree_select(self, _event: tk.Event) -> None:
        selected = self.items_tree.selection()
        if selected:
            self._line_to_form(self._line_from_tree(selected[0]))

    def update_selected_line(self) -> None:
        try:
            line = self._line_from_form()
        except Exception as exc:
            messagebox.showerror("Invalid item", str(exc))
            return
        selected = self.items_tree.selection()
        values = self._line_values(line)
        if selected:
            self.items_tree.item(selected[0], values=values)
        else:
            self.items_tree.insert("", tk.END, values=values)
        self.set_status("Updated detected item.")

    def remove_selected_line(self) -> None:
        for item_id in self.items_tree.selection():
            self.items_tree.delete(item_id)
        self.set_status("Removed selected item.")

    def _apply_form_to_selected_line(self) -> None:
        selected = self.items_tree.selection()
        if selected:
            line = self._line_from_form()
            self.items_tree.item(selected[0], values=self._line_values(line))

    def _default_category(self) -> str:
        return self.reference.categories[0] if self.reference.categories else ""

    def clear_form(self) -> None:
        self.text_box.delete("1.0", tk.END)
        self.item_var.set("")
        self.date_var.set("")
        self.unit_price_var.set("")
        self.quantity_var.set("1")
        self.price_var.set("")
        self.confidence_var.set("-")
        for item_id in self.items_tree.get_children():
            self.items_tree.delete(item_id)
        self.order_lines = []
        self.category_var.set("")
        self.set_status("Cleared.")

    def _store(self) -> BalanceWorkbook:
        return BalanceWorkbook(Path(self.workbook_var.get()), self.sheet_var.get().strip() or DEFAULT_SHEET)

    def _ocr_languages(self) -> str:
        selected = self.ocr_language_var.get()
        if selected == "Chinese":
            return "chi_sim"
        if selected == "English":
            return "eng"
        return "chi_sim+eng"

    def set_status(self, text: str) -> None:
        self.status_var.set(text)


def main() -> None:
    app = OrderRecognizerApp()
    app.mainloop()


def _format_quantity(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


if __name__ == "__main__":
    main()
