import json
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.db import transaction
from main.constants import (DEPOSIT_TYPE_DEPOSIT, DEPOSIT_TYPE_FINAL, DEPOSIT_TYPE_FULL)
from main.models import (Client, ClientOrder, DepositClient, DepositFactory, DepositType, FactoryOrder, Order, Transport)

SHEET_TAB_NAME = "Sheet1"
HEADER_ROW = 6

SHEET_COLUMNS = {
    "contract_number": "SUTARTIES NR.",
    "factory_order_number": "GAMYKLOS UŽSAKYMO Nr.",
    "factory_order_amount": "GAMYKLOS SUMA",
    "factory_deposit_amount": "GAMYKLOS AVANSO SUMA",
    "factory_final_amount": "GAMYKLAI GALUTINIS MOKĖJIMAS",
    "factory_packaging_cost": "PAKUOTĖS KAINA",
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
    Sheet amounts come through like '4,176.00 €' or '-'.
    A dash means zero/not entered.
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
    """Parse supported sheet date formats."""
    if not value:
        return None

    value = str(value).strip()

    if value in ("-", "—"):
        return None

    # Date range: 19-21/08/2026 -> use start date
    range_match = re.match(
        r"^(\d{1,2})-(\d{1,2})/(\d{1,2})/(\d{4})$",
        value,
    )

    if range_match:
        start_day, end_day, month, year = range_match.groups()

        try:
            return datetime.strptime(
                f"{year}-{month}-{start_day}",
                "%Y-%m-%d",
            ).date()
        except ValueError:
            return None

    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y",):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def is_paid(amount, total):
    """Paid if total is zero, or paid amount equals total."""
    if total is not None and total == 0:
        return True

    if amount is not None and total is not None and amount == total:
        return True

    return False


def load_sheet_id(sheet_id_json_path):
    with open(sheet_id_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sheet_id = data.get("sheet_id")

    if not sheet_id:
        raise ValueError(f"'{sheet_id_json_path}' does not contain a 'sheet_id' key.")

    return sheet_id


def get_sheet_rows():
    import gspread
    from google.oauth2 import service_account

    creds_path = os.environ["GOOGLE_SHEETS_CREDENTIALS_PATH"]
    sheet_id_json_path = os.environ["GOOGLE_SHEET_ID_PATH"]

    sheet_id = load_sheet_id(sheet_id_json_path)

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    creds = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=scopes,
    )

    client = gspread.authorize(creds)

    sheet = client.open_by_key(sheet_id)
    worksheet = sheet.worksheet(SHEET_TAB_NAME)

    return worksheet.get_all_records(head=HEADER_ROW)


def update_if_changed(obj, defaults):
    """
    Update an existing object only when one or more values changed.
    """
    changed_fields = []

    for field, new_value in defaults.items():
        if getattr(obj, field) != new_value:
            setattr(obj, field, new_value)
            changed_fields.append(field)

    if changed_fields:
        obj.save(update_fields=changed_fields)
        return True

    return False


def get_or_create_then_update(model, lookup, defaults):
    """
    Create the object if it does not exist.

    If it already exists, only update fields whose values changed.

    Returns:
        object, created, updated
    """
    obj, created = model.objects.get_or_create(
        **lookup,
        defaults=defaults,
    )

    if created:
        return obj, True, False

    updated = update_if_changed(obj, defaults)

    return obj, False, updated


class Command(BaseCommand):
    help = "Sync orders from the Google Sheet (Sheet1) into the database."

    def handle(self, *args, **options):
        self._warnings = []

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
                "updated": 0,
                "warnings": [],
            }

        synced = 0
        skipped = 0
        updated = 0
        seen_contracts = set()

        contract_numbers = [
            str(
                r.get(
                    SHEET_COLUMNS["contract_number"],
                    "",
                )
            ).strip()
            for r in rows
            if str(
                r.get(
                    SHEET_COLUMNS["contract_number"],
                    "",
                )
            ).strip()
        ]

        counts = {}

        for contract in contract_numbers:
            counts[contract] = counts.get(contract, 0) + 1

        duplicate_count = sum(count - 1 for count in counts.values() if count > 1)

        duplicated_contracts = {
            contract for contract, count in counts.items() if count > 1
        }

        # These don't change during a sync, so only look them up once.
        deposit_type_deposit, _ = DepositType.objects.get_or_create(
            type_name=DEPOSIT_TYPE_DEPOSIT
        )

        deposit_type_final, _ = DepositType.objects.get_or_create(
            type_name=DEPOSIT_TYPE_FINAL
        )

        deposit_type_full, _ = DepositType.objects.get_or_create(
            type_name=DEPOSIT_TYPE_FULL
        )

        deposit_types = {
            "deposit": deposit_type_deposit,
            "final": deposit_type_final,
            "full": deposit_type_full,
        }

        for row in rows:
            contract_number = str(
                row.get(
                    SHEET_COLUMNS["contract_number"],
                    "",
                )
            ).strip()

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
                    row_updated = self._sync_row(
                        row,
                        contract_number,
                        deposit_types,
                    )

                synced += 1

                if row_updated:
                    updated += 1

            except Exception as exc:
                skipped += 1

                msg = f"Skipped row '{contract_number}': {exc}"

                self.stderr.write(self.style.WARNING(msg))

                self._warnings.append(msg)

        deleted_count, _ = Order.objects.exclude(
            contract_number__in=seen_contracts
        ).delete()

        if duplicated_contracts:
            msg = (
                "Found duplicate contract numbers, skipped syncing "
                "them (existing data left untouched): "
                f"{', '.join(sorted(duplicated_contracts))}"
            )

            self.stderr.write(self.style.WARNING(msg))

            self._warnings.append(msg)

        summary = (
            f"Sync complete. {synced} rows synced, "
            f"{skipped} skipped, "
            f"{duplicate_count} duplicates, "
            f"{deleted_count} deleted, "
            f"{updated} rows changed."
        )

        self.stdout.write(self.style.SUCCESS(summary))

        result = {
            "status": "success",
            "summary": summary,
            "synced": synced,
            "skipped": skipped,
            "duplicates": duplicate_count,
            "deleted": deleted_count,
            "updated": updated,
            "warnings": self._warnings,
        }

        return json.dumps(result)

    def _sync_row(
        self,
        row,
        contract_number,
        deposit_types,
    ):
        c = SHEET_COLUMNS

        row_changed = False

        # ---------------------------------------------------------
        # Client
        # ---------------------------------------------------------

        client_name = str(row.get(c["client"], "")).strip()

        if not client_name:
            raise ValueError("missing client name")

        client_obj, _ = Client.objects.get_or_create(client_name=client_name)

        # ---------------------------------------------------------
        # Order
        # ---------------------------------------------------------

        order_defaults = {
            "client": client_obj,
            "country": str(row.get(c["country"], "")).strip(),
        }

        order, _, changed = get_or_create_then_update(
            Order,
            {"contract_number": contract_number},
            order_defaults,
        )

        row_changed |= changed

        # ---------------------------------------------------------
        # Client order
        # ---------------------------------------------------------

        client_total = parse_decimal(row.get(c["client_total_amount"]))

        client_deposit_amount = parse_decimal(row.get(c["client_deposit_amount"]))

        client_final_amount = parse_decimal(row.get(c["client_final_amount"]))

        deposit = client_deposit_amount or Decimal("0")
        final = client_final_amount or Decimal("0")
        total = client_total or Decimal("0")

        payment_type = str(row.get(c["client_payment_type"], "")).strip()

        client_order_defaults = {
            "client": client_obj,
            "client_representative": str(
                row.get(c["client_representative"], "")
            ).strip(),
            "client_contact": str(row.get(c["client_contact"], "")).strip(),
            "total_amount": client_total,
            "payment_type": payment_type,
        }

        client_order, _, changed = get_or_create_then_update(
            ClientOrder,
            {"order": order},
            client_order_defaults,
        )

        row_changed |= changed

        deposit_type_deposit = deposit_types["deposit"]
        deposit_type_final = deposit_types["final"]
        deposit_type_full = deposit_types["full"]

        paid_amount = deposit + final

        def _cell_is_blank(raw_value):
            text = (
                str(raw_value).replace("€", "").strip() if raw_value is not None else ""
            )

            return text in ("", "-", "—")

        has_client_amount = not (
            _cell_is_blank(row.get(c["client_total_amount"]))
            and _cell_is_blank(row.get(c["client_deposit_amount"]))
            and _cell_is_blank(row.get(c["client_final_amount"]))
        )

        if not has_client_amount:
            deleted_count, _ = DepositClient.objects.filter(
                client_order=client_order
            ).delete()

            if deleted_count:
                row_changed = True

        elif client_total is not None and client_total < 0:
            msg = (
                f"Negative client total amount for contract "
                f"{contract_number}: {client_total}. "
                "Treating as no client deposit info."
            )

            self.stderr.write(self.style.WARNING(msg))

            self._warnings.append(msg)

            deleted_count, _ = DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__in=[
                    deposit_type_deposit,
                    deposit_type_final,
                ],
            ).delete()

            if deleted_count:
                row_changed = True

            client_total = None
            client_deposit_amount = None
            client_final_amount = None

        elif payment_type == "Visa suma":
            _, _, changed = get_or_create_then_update(
                DepositClient,
                {
                    "client_order": client_order,
                    "deposit_type": deposit_type_full,
                },
                {
                    "amount": total,
                    "payment_due_by": None,
                    "is_paid": is_paid(
                        paid_amount,
                        total,
                    ),
                },
            )

            row_changed |= changed

            deleted_count, _ = DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__in=[
                    deposit_type_deposit,
                    deposit_type_final,
                ],
            ).delete()

            if deleted_count:
                row_changed = True

        elif payment_type == "Po pristatymo":
            _, _, changed = get_or_create_then_update(
                DepositClient,
                {
                    "client_order": client_order,
                    "deposit_type": deposit_type_full,
                },
                {
                    "amount": total,
                    "payment_due_by": parse_date(row.get(c["client_final_due_date"])),
                    "is_paid": is_paid(
                        paid_amount,
                        total,
                    ),
                },
            )

            row_changed |= changed

            deleted_count, _ = DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__in=[
                    deposit_type_deposit,
                    deposit_type_final,
                ],
            ).delete()

            if deleted_count:
                row_changed = True

        elif payment_type == "Avansas":
            deposit_covers_full_total = total > 0 and deposit >= total

            _, _, changed = get_or_create_then_update(
                DepositClient,
                {
                    "client_order": client_order,
                    "deposit_type": deposit_type_deposit,
                },
                {
                    "amount": deposit,
                    "payment_due_by": None,
                    "is_paid": deposit > 0,
                },
            )

            row_changed |= changed

            _, _, changed = get_or_create_then_update(
                DepositClient,
                {
                    "client_order": client_order,
                    "deposit_type": deposit_type_final,
                },
                {
                    "amount": final,
                    "payment_due_by": parse_date(row.get(c["client_final_due_date"])),
                    "is_paid": (final > 0 or deposit_covers_full_total),
                },
            )

            row_changed |= changed

            deleted_count, _ = DepositClient.objects.filter(
                client_order=client_order,
                deposit_type=deposit_type_full,
            ).delete()

            if deleted_count:
                row_changed = True

        elif payment_type == "":
            msg = (
                f"Contract {contract_number} has client amounts "
                "filled in but no MOKĖJIMO TIPAS selected — "
                "clearing existing client deposit tracking for "
                "this order until a payment type is set."
            )

            self.stderr.write(self.style.WARNING(msg))

            self._warnings.append(msg)

            deleted_count, _ = DepositClient.objects.filter(
                client_order=client_order
            ).delete()

            if deleted_count:
                row_changed = True

        else:
            raise ValueError(
                f"Unknown payment type '{payment_type}' "
                f"for contract {contract_number}"
            )

        # ---------------------------------------------------------
        # Factory order
        # ---------------------------------------------------------

        factory_order_amount = parse_decimal(row.get(c["factory_order_amount"]))

        factory_deposit_amount = parse_decimal(row.get(c["factory_deposit_amount"]))

        factory_final_amount = parse_decimal(row.get(c["factory_final_amount"]))

        raw_packaging_cost = row.get(c["factory_packaging_cost"])

        factory_packaging_cost = parse_decimal(raw_packaging_cost)

        factory_order_defaults = {
            "factory_order_number": str(row.get(c["factory_order_number"], "")).strip(),
            "order_amount": factory_order_amount,
            "production_start_date": parse_date(row.get(c["production_start_date"])),
            "production_end_date": parse_date(row.get(c["production_end_date"])),
        }

        factory_order, _, changed = get_or_create_then_update(
            FactoryOrder,
            {"order": order},
            factory_order_defaults,
        )

        row_changed |= changed

        if _cell_is_blank(raw_packaging_cost):
            factory_paid_amount = (factory_deposit_amount or Decimal("0")) + (
                factory_final_amount or Decimal("0")
            )
        else:
            factory_paid_amount = (
                (factory_deposit_amount or Decimal("0"))
                + (factory_final_amount or Decimal("0"))
                + (factory_packaging_cost or Decimal("0"))
            )

        factory_fully_paid = is_paid(
            factory_paid_amount,
            factory_order_amount,
        )

        _, _, changed = get_or_create_then_update(
            DepositFactory,
            {
                "factory_order": factory_order,
                "deposit_type": deposit_type_deposit,
            },
            {
                "amount": factory_deposit_amount,
                "is_paid": (
                    factory_fully_paid
                    or is_paid(
                        factory_deposit_amount,
                        factory_order_amount,
                    )
                ),
            },
        )

        row_changed |= changed

        _, _, changed = get_or_create_then_update(
            DepositFactory,
            {
                "factory_order": factory_order,
                "deposit_type": deposit_type_final,
            },
            {
                "amount": factory_final_amount,
                "is_paid": (
                    factory_fully_paid
                    or is_paid(
                        factory_final_amount,
                        factory_order_amount,
                    )
                ),
            },
        )

        row_changed |= changed

        # ---------------------------------------------------------
        # Transport
        # ---------------------------------------------------------

        transport_defaults = {
            "courier": str(row.get(c["courier"], "")).strip(),
            "delivery_address": str(row.get(c["client_shipment_address"], "")).strip(),
            "delivery_price": parse_decimal(row.get(c["shipment_cost"])),
            "delivery_date": parse_date(row.get(c["shipment_delivery_date"])),
        }

        _, _, changed = get_or_create_then_update(
            Transport,
            {"order": order},
            transport_defaults,
        )

        row_changed |= changed

        return row_changed
