from pathlib import Path

from libs.device_importer import load_devices_from_file
from openpyxl import Workbook


def test_load_devices_from_csv(tmp_path: Path):
    csv_path = tmp_path / "devices.csv"
    csv_path.write_text("SN,Name,Type\nSN1,Device1,Phone\n", encoding="utf-8")

    rows = load_devices_from_file(str(csv_path))
    assert rows == [{"SN": "SN1", "Name": "Device1", "Type": "Phone"}]


def test_load_devices_from_xlsx(tmp_path: Path):
    xlsx_path = tmp_path / "devices.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["SN", "Name", "Type"])
    ws.append(["SN2", "Device2", "Tablet"])
    wb.save(xlsx_path)

    rows = load_devices_from_file(str(xlsx_path))
    assert rows == [{"SN": "SN2", "Name": "Device2", "Type": "Tablet"}]
