import json
import os

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")  # весь JSON-ключ одной строкой (для Railway/облака)
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB", "Заявки")

_HEADERS = ["Дата", "Имя", "Телефон", "Username", "Что нужно", "Telegram ID", "Источник (группа)"]

_client = None
_sheet = None


def _load_credentials() -> Credentials:
    # На Railway удобнее хранить весь JSON-ключ в переменной окружения,
    # чем коммитить файл credentials.json в репозиторий.
    if GOOGLE_CREDENTIALS_JSON:
        info = json.loads(GOOGLE_CREDENTIALS_JSON)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)


def _get_sheet():
    global _client, _sheet
    if _sheet is not None:
        return _sheet

    if not GOOGLE_SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID не задан в .env")

    creds = _load_credentials()
    _client = gspread.authorize(creds)
    spreadsheet = _client.open_by_key(GOOGLE_SHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(GOOGLE_SHEET_TAB)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=GOOGLE_SHEET_TAB, rows=1000, cols=len(_HEADERS))
        worksheet.append_row(_HEADERS)

    # Add headers if the sheet is empty
    if worksheet.row_count == 0 or not worksheet.get_all_values():
        worksheet.append_row(_HEADERS)

    _sheet = worksheet
    return _sheet


def append_lead(row: list) -> None:
    """Append a single lead row: [timestamp, full_name, phone, username, need, tg_id, source]"""
    sheet = _get_sheet()
    sheet.append_row(row, value_input_option="USER_ENTERED")
