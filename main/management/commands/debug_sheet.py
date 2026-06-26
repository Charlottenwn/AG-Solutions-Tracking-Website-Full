"""
Debug helper: prints exactly what gspread sees for Sheet1, so we can compare
against SHEET_COLUMNS in sync_sheet.py.

Usage:
    python manage.py debug_sheet
"""
import os

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print raw headers and first data row from the Google Sheet for debugging."

    def handle(self, *args, **options):
        import gspread
        from google.oauth2.service_account import Credentials

        creds_path = os.environ["GOOGLE_SHEETS_CREDENTIALS_PATH"]
        sheet_id_json_path = os.environ["GOOGLE_SHEET_ID_PATH"]

        import json
        with open(sheet_id_json_path, "r", encoding="utf-8") as f:
            sheet_id = json.load(f)["sheet_id"]

        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        client = gspread.authorize(creds)

        sheet = client.open_by_key(sheet_id)
        self.stdout.write(f"Opened spreadsheet: {sheet.title}")
        self.stdout.write(f"Worksheets found: {[ws.title for ws in sheet.worksheets()]}")

        worksheet = sheet.worksheet("Sheet1")

        self.stdout.write("\n--- Raw row 5 (expected header row) ---")
        self.stdout.write(repr(worksheet.row_values(5)))

        self.stdout.write("\n--- Raw row 6 (expected first data row) ---")
        self.stdout.write(repr(worksheet.row_values(6)))

        self.stdout.write("\n--- get_all_records(head=5) result ---")
        records = worksheet.get_all_records(head=5)
        self.stdout.write(f"Number of records: {len(records)}")
        if records:
            self.stdout.write("First record:")
            self.stdout.write(repr(records[0]))