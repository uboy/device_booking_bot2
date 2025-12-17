from __future__ import annotations

import csv
import os
from typing import Dict, List

from openpyxl import load_workbook

REQUIRED_COLUMNS = ("SN", "Name", "Type")


def _read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not set(REQUIRED_COLUMNS).issubset(reader.fieldnames):
            raise ValueError("В файле должны быть колонки SN, Name, Type")
        rows: List[Dict[str, str]] = []
        for row in reader:
            rows.append(
                {
                    "SN": (row.get("SN") or "").strip(),
                    "Name": (row.get("Name") or "").strip(),
                    "Type": (row.get("Type") or "").strip(),
                }
            )
        return rows


def _read_xlsx(path: str) -> List[Dict[str, str]]:
    wb = load_workbook(path, data_only=True)
    sheet = wb.active
    header = [str(cell.value).strip() if cell.value is not None else "" for cell in next(sheet.iter_rows(max_row=1))]
    if not set(REQUIRED_COLUMNS).issubset(header):
        raise ValueError("В файле должны быть колонки SN, Name, Type")

    # Сопоставление индексов колонок
    col_index = {name: header.index(name) for name in REQUIRED_COLUMNS}

    rows: List[Dict[str, str]] = []
    for row in sheet.iter_rows(min_row=2):
        def _get(name: str) -> str:
            value = row[col_index[name]].value
            return "" if value is None else str(value).strip()

        rows.append({"SN": _get("SN"), "Name": _get("Name"), "Type": _get("Type")})
    return rows


def load_devices_from_file(path: str) -> List[Dict[str, str]]:
    """Читает CSV или XLSX с колонками SN, Name, Type и возвращает список словарей."""
    ext = os.path.splitext(path.lower())[1]
    if ext == ".csv":
        return _read_csv(path)
    if ext in (".xlsx", ".xls"):
        return _read_xlsx(path)
    raise ValueError("Поддерживаются только CSV или XLSX")
