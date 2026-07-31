"""
Sync Google Sheet (single tab "Sheet1") into Postgres.

Usage:
    python manage.py sync_sheet

Required environment variables:
    GOOGLE_SHEETS_CREDENTIALS_PATH  - path to the service account credentials.json
    GOOGLE_SHEET_ID_PATH            - path to a JSON file containing {"sheet_id": "..."}

Sheet1 columns (left to right), confirmed via debug_sheet (actual headers
are in Lithuanian):
    SUTARTIES NR., GAMYKLOS UZSAKYMO Nr., GAMYKLOS SUMA, GAMYKLOS AVANSO SUMA,
    GAMYKLAI GALUTINIS MOKEJIMAS, KLIENTAS, KLIENTO ATSTOVAS, GAMYBOS PRADZIA,
    GAMYBOS PABAIGA, PRISTATYMO DATA, SALIS, SUMA, AVANSAS, AVANSO TERMINAS,
    GALUTINIS MOKEJIMAS, GALUTINIO MOK TERMINAS, PRISTATYMO ADRESAS,
    KONTAKTAS, VEZEJAS DSV/NTEX, VEZIMO KAINA

Paid inference rule (as specified): a deposit/final payment is considered paid
if the relevant total amount is 0, or the amount paid equals the total amount.
This is recalculated on every sync run — it is NOT something to hand-edit in
the admin afterward, since the next sync will recompute and overwrite it.

NOTE: column header text in the actual sheet must match SHEET_COLUMNS below
exactly (gspread's get_all_records() keys results by header row text). If your
real headers differ even slightly (typos, extra spaces, parentheses), update
SHEET_COLUMNS to match — don't silently rename your sheet to fit the code.
"""
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.db import transaction
from collections import Counter
import json
from main.models import (
    Client, Order, ClientOrder, FactoryOrder,
    DepositType, DepositClient, DepositFactory, Transport,
)
from constants import (DEPOSIT_TYPE_DEPOSIT, DEPOSIT_TYPE_FINAL, DEPOSIT_TYPE_FULL)

SHEET_TAB_NAME = "Sheet1"
HEADER_ROW = 6

SHEET_COLUMNS = {
    "contract_number": "SUTARTIES NR.",
    "factory_order_number": "GAMYKLOS UŽSAKYMO Nr.",
    "factory_order_amount": "GAMYKLOS SUMA",
    "factory_deposit_amount": "GAMYKLOS AVANSO SUMA",
    "factory_final_amount": "GAMYKLAI GALUTINIS MOKĖJIMAS",
    "client": "KLIENTAS",
    "client_representative": "KLIENTO ATSTOVAS",
    "production_start_date": "GAMYBOS PRADŽIA",
    "production_end_date": "GAMYBOS PABAIGA",
    "shipment_delivery_date": "PRISTATYMO DATA",
    "country": "ŠALIS",
    "client_total_amount": "SUMA",
    "client_payment_type": "MOKĖJIMO TIPAS",
    "client_deposit_amount": "AVANSAS",
    "client_final_amount": "GALUTINIS MOKĖJIMAS",
    "client_final_due_date": "GALUTINIO MOK TERMINAS",
    "client_shipment_address": "PRISTATYMO ADRESAS",
    "client_contact": "KONTAKTAS",
    "courier": "VEŽĖJAS DSV/NTEX",
    "shipment_cost": "VEŽIMO KAINA",
}


def parse_decimal(value):
    """
    Sheet amounts come through like '  4,176.00  € ' or '  -    € ' (a dash
    means zero/not yet entered, not a parsing failure).
    """
    if value in (None, ""):
        return None
    text = str(value).replace("€", "").strip()
    text = text.replace(" ", "")
    if text in ("", "-", "—"):
        return Decimal("0")
    text = text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date(value):
    """Sheet dates come through like '2026.02.09'; '-' means not set."""
    if not value:
        return None
    value = str(value).strip()
    if value in ("-", "—"):
        return None
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def is_paid(amount, total):
    """Paid if the total is zero, or the amount paid matches the total."""
    if total is not None and total == 0:
        return True
    if amount is not None and total is not None and amount == total:
        return True
    return False


def load_sheet_id(sheet_id_json_path):
    """
    GOOGLE_SHEET_ID_PATH points at a JSON file like:
        { "sheet_id": "1AbCxyz...actualSheetId..." }
    rather than the env var holding the ID directly.
    """
    import json
    with open(sheet_id_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sheet_id = data.get("sheet_id")
    if not sheet_id:
        raise ValueError(
            f"'{sheet_id_json_path}' does not contain a 'sheet_id' key."
        )
    return sheet_id


def get_sheet_rows():
    import gspread
    from google.oauth2 import service_account
    
    creds_path = os.environ["GOOGLE_SHEETS_CREDENTIALS_PATH"]
    sheet_id_json_path = os.environ["GOOGLE_SHEET_ID_PATH"]
    sheet_id = load_sheet_id(sheet_id_json_path)

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(sheet_id)
    worksheet = sheet.worksheet(SHEET_TAB_NAME)
    return worksheet.get_all_records(head=HEADER_ROW)


class Command(BaseCommand):
    help = "Sync orders from the Google Sheet (Sheet1) into the database."

    def handle(self, *args, **options):
        self._warnings = []  # collected across handle() and _sync_row()

        rows = get_sheet_rows()

        if not rows:
            msg = (
                "Sheet returned 0 rows — aborting sync without deleting "
                "anything from the database. This usually means the "
                "sheet was accidentally cleared, the wrong tab/sheet ID "
                "is configured, or the Sheets API call failed silently. "
                "If the sheet is genuinely meant to be empty, clear the "
                "database manually instead of relying on sync."
            )
            self.stderr.write(self.style.ERROR(msg))
            return {
                "status": "aborted",
                "reason": msg,
                "synced": 0,
                "skipped": 0,
                "duplicates": 0,
                "deleted": 0,
                "warnings": [],
            }

        synced = 0
        skipped = 0
        seen_contracts = set()

        contract_numbers = [
            str(r.get(SHEET_COLUMNS["contract_number"], "")).strip()
            for r in rows
            if str(r.get(SHEET_COLUMNS["contract_number"], "")).strip()
        ]

        counts = Counter(contract_numbers)
        duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
        duplicated_contracts = [contract for contract, count in counts.items() if count > 1]

        for row in rows:
            contract_number = str(row.get(SHEET_COLUMNS["contract_number"], "")).strip()

            if not contract_number:
                skipped += 1
                continue

            if contract_number in duplicated_contracts:
                seen_contracts.add(contract_number)
                skipped += 1
                continue

            seen_contracts.add(contract_number)

            try:
                with transaction.atomic():
                    self._sync_row(row, contract_number)
                synced += 1

            except Exception as exc:
                skipped += 1
                msg = f"Skipped row '{contract_number}': {exc}"
                self.stderr.write(self.style.WARNING(msg))
                self._warnings.append(msg)

        deleted_count, _ = (
            Order.objects
            .exclude(contract_number__in=seen_contracts)
            .delete()
        )

        if duplicated_contracts:
            msg = (
                f"Found duplicate contract numbers, skipped syncing "
                f"them (existing data left untouched): "
                f"{', '.join(sorted(duplicated_contracts))}"
            )
            self.stderr.write(self.style.WARNING(msg))
            self._warnings.append(msg)

        summary = (
            f"Sync complete. {synced} rows synced, {skipped} skipped, "
            f"{duplicate_count} duplicates, {deleted_count} deleted."
        )
        self.stdout.write(self.style.SUCCESS(summary))

        result = {
            "status": "success",
            "summary": summary,
            "synced": synced,
            "skipped": skipped,
            "duplicates": duplicate_count,
            "deleted": deleted_count,
            "warnings": self._warnings,
        }
        return json.dumps(result)

    def _sync_row(self, row, contract_number):
        c = SHEET_COLUMNS

        client_name = str(row.get(c["client"], "")).strip()
        if not client_name:
            raise ValueError("missing client name")
        client_obj, _ = Client.objects.get_or_create(client_name=client_name)

        order, _ = Order.objects.update_or_create(
            contract_number=contract_number,
            defaults={
                "client": client_obj,
                "country": str(row.get(c["country"], "")).strip(),
            },
        )

        # --- Client side ---
        raw_total = row.get(c["client_total_amount"])
        raw_deposit = row.get(c["client_deposit_amount"])
        raw_final = row.get(c["client_final_amount"])
        
        client_total = parse_decimal(raw_total)
        client_deposit_amount = parse_decimal(raw_deposit)
        client_final_amount = parse_decimal(raw_final)
        
        deposit = client_deposit_amount or Decimal("0")
        final = client_final_amount or Decimal("0")
        total = client_total or Decimal("0")
        
        payment_type = str(
            row.get(c["client_payment_type"], "")
            ).strip()
        
        client_order, _ = ClientOrder.objects.update_or_create(
            order=order,
            defaults={
                "client": client_obj,
                "client_representative": str(row.get(c["client_representative"], "")).strip(),
                "client_contact": str(row.get(c["client_contact"], "")).strip(),
                "total_amount": client_total,
                "payment_type": payment_type,
            },
        )
        deposit_type_deposit, _ = DepositType.objects.get_or_create(
            type_name=DEPOSIT_TYPE_DEPOSIT
        )
        deposit_type_final, _ = DepositType.objects.get_or_create(
            type_name=DEPOSIT_TYPE_FINAL
        )
        deposit_type_full, _ = DepositType.objects.get_or_create(
            type_name=DEPOSIT_TYPE_FULL
        )
        
        paid_amount = deposit + final

        def _cell_is_blank(raw_value):
            text = str(raw_value).replace("€", "").strip() if raw_value is not None else ""
            return text in ("", "-", "—")

        has_client_amount = not (
            _cell_is_blank(raw_total)
            and _cell_is_blank(raw_deposit)
            and _cell_is_blank(raw_final)
        )
        
        if not has_client_amount:
            DepositClient.objects.filter(client_order=client_order).delete()
            
        elif client_total is not None and client_total < 0:
            msg = (
                    f"Negative client total amount for contract {contract_number}: {client_total}."
                    f" Treating as no client deposit info."
                )
            self.stderr.write(self.style.WARNING(msg))
            self._warnings.append(msg)
            client_total = None
            client_deposit_amount = None
            client_final_amount = None
            
            DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__in=[deposit_type_deposit, deposit_type_final]
            ).delete()
            
        elif payment_type == "Visa suma":
            DepositClient.objects.update_or_create(
                client_order=client_order,
                deposit_type=deposit_type_full,
                defaults={
                    "amount": total,
                    "payment_due_by": None,
                    "is_paid": is_paid(paid_amount, total)
                },
            )
            
            DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__in=[deposit_type_deposit, deposit_type_final]
            ).delete()
            
        elif payment_type == "Po pristatymo":
            
            DepositClient.objects.update_or_create(
                client_order=client_order,
                deposit_type=deposit_type_full,
                defaults={
                    "amount": total,
                    "payment_due_by": parse_date(row.get(c["client_final_due_date"])),
                    "is_paid": is_paid(paid_amount, total)
                },
            )
            
            DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__in=[deposit_type_deposit, deposit_type_final],
            ).delete()
            
        elif payment_type == "Avansas":
            
            DepositClient.objects.update_or_create(
                client_order=client_order,
                deposit_type=deposit_type_deposit,
                defaults={
                    "amount": deposit,
                    "payment_due_by": None,
                    "is_paid": deposit > 0,
                },
            )
            
            DepositClient.objects.update_or_create(
                client_order=client_order,
                deposit_type=deposit_type_final,
                defaults={
                    "amount": final,
                    "payment_due_by": parse_date(row.get(c["client_final_due_date"])),
                    "is_paid": final > 0,
                },
            )
            
            DepositClient.objects.filter(
                client_order=client_order,
                deposit_type=deposit_type_full
            ).delete()
            
        elif payment_type == "":
            msg = (
                    f"Contract {contract_number} has client amounts filled in "
                    f"but no MOKĖJIMO TIPAS selected — clearing existing client "
                    f"deposit tracking for this order until a payment type is set."
                )
            self.stderr.write(self.style.WARNING(msg))
            self._warnings.append(msg)
            DepositClient.objects.filter(client_order=client_order).delete()
            
        else:
            raise ValueError(
                f"Unknown payment type '{payment_type}' "
                f"for contract {contract_number}"
            )
            
        # --- Factory side ---
        factory_order_amount = parse_decimal(row.get(c["factory_order_amount"]))
        factory_deposit_amount = parse_decimal(row.get(c["factory_deposit_amount"]))
        factory_final_amount = parse_decimal(row.get(c["factory_final_amount"]))

        factory_order, _ = FactoryOrder.objects.update_or_create(
            order=order,
            defaults={
                "factory_order_number": str(row.get(c["factory_order_number"], "")).strip(),
                "order_amount": factory_order_amount,
                "production_start_date": parse_date(row.get(c["production_start_date"])),
                "production_end_date": parse_date(row.get(c["production_end_date"])),
            },
        )

        factory_paid_amount = (factory_deposit_amount or Decimal("0")) + (factory_final_amount or Decimal("0"))
        factory_fully_paid = is_paid(factory_paid_amount, factory_order_amount)
        
        DepositFactory.objects.update_or_create(
            factory_order=factory_order,
            deposit_type=deposit_type_deposit,
            defaults={
                "amount": factory_deposit_amount,
                "is_paid": factory_fully_paid or is_paid(factory_deposit_amount, factory_order_amount),
            },
        )
        DepositFactory.objects.update_or_create(
            factory_order=factory_order,
            deposit_type=deposit_type_final,
            defaults={
                "amount": factory_final_amount,
                "is_paid": factory_fully_paid or is_paid(factory_final_amount, factory_order_amount),
            },
        )

        # --- Transport ---
        Transport.objects.update_or_create(
            order=order,
            defaults={
                "courier": str(row.get(c["courier"], "")).strip(),
                "delivery_address": str(row.get(c["client_shipment_address"], "")).strip(),
                "delivery_price": parse_decimal(row.get(c["shipment_cost"])),
                "delivery_date": parse_date(row.get(c["shipment_delivery_date"])),
            },
        )