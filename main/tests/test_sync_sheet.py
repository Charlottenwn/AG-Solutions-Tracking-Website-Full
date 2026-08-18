"""
main/tests/test_sync_sheet.py

Tests for main/management/commands/sync_sheet.py.
"""

import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, SimpleTestCase

from main.management.commands.sync_sheet import (
    SHEET_COLUMNS,
    Command,
    get_sheet_rows,
    parse_decimal,
    parse_date,
    is_paid,
    load_sheet_id,
)
from main.models import (
    Client,
    Order,
    ClientOrder,
    FactoryOrder,
    DepositType,
    DepositClient,
    DepositFactory,
    Transport,
)
from main.constants import (
    DEPOSIT_TYPE_DEPOSIT,
    DEPOSIT_TYPE_FINAL,
    DEPOSIT_TYPE_FULL,
)


class ParseDecimalTests(SimpleTestCase):
    def test_none_returns_none(self):
        self.assertIsNone(parse_decimal(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_decimal(""))

    def test_plain_number_string(self):
        self.assertEqual(parse_decimal("4176"), Decimal("4176"))

    def test_number_with_thousands_separator(self):
        self.assertEqual(parse_decimal("4,176.00"), Decimal("4176.00"))

    def test_number_with_euro_sign(self):
        self.assertEqual(parse_decimal("4,176.00 €"), Decimal("4176.00"))

    def test_number_with_leading_trailing_whitespace(self):
        self.assertEqual(
            parse_decimal("  4,176.00  €  "),
            Decimal("4176.00"),
        )

    def test_dash_means_zero(self):
        self.assertEqual(parse_decimal("-"), Decimal("0"))
        self.assertEqual(parse_decimal("  -  €  "), Decimal("0"))

    def test_em_dash_means_zero(self):
        self.assertEqual(parse_decimal("—"), Decimal("0"))

    def test_unparseable_string_returns_none(self):
        self.assertIsNone(parse_decimal("not a number"))

    def test_negative_number(self):
        self.assertEqual(parse_decimal("-500"), Decimal("-500"))


class ParseDateTests(SimpleTestCase):
    def test_none_returns_none(self):
        self.assertIsNone(parse_date(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_date(""))

    def test_dash_returns_none(self):
        self.assertIsNone(parse_date("-"))
        self.assertIsNone(parse_date("—"))

    def test_dot_separated_format(self):
        result = parse_date("2026.02.09")
        self.assertEqual(result.isoformat(), "2026-02-09")

    def test_hyphen_separated_iso_format(self):
        result = parse_date("2026-02-09")
        self.assertEqual(result.isoformat(), "2026-02-09")

    def test_slash_separated_dmy_format(self):
        result = parse_date("09/02/2026")
        self.assertEqual(result.isoformat(), "2026-02-09")

    def test_dot_separated_dmy_format(self):
        result = parse_date("09.02.2026")
        self.assertEqual(result.isoformat(), "2026-02-09")

    def test_slash_separated_mdy_format(self):
        result = parse_date("02/09/2026")
        self.assertEqual(result.isoformat(), "2026-02-09")

    def test_date_range_uses_start_date(self):
        result = parse_date("19-21/08/2026")
        self.assertEqual(result.isoformat(), "2026-08-19")

    def test_invalid_date_range_returns_none(self):
        self.assertIsNone(parse_date("99-21/08/2026"))

    def test_unrecognized_format_returns_none(self):
        self.assertIsNone(parse_date("not-a-date"))

    def test_invalid_date_returns_none(self):
        self.assertIsNone(parse_date("2026.99.99"))

    def test_whitespace_stripped_before_parsing(self):
        result = parse_date("  2026.02.09  ")
        self.assertEqual(result.isoformat(), "2026-02-09")


class IsPaidTests(SimpleTestCase):
    def test_zero_total_is_always_paid(self):
        self.assertTrue(is_paid(None, Decimal("0")))
        self.assertTrue(is_paid(Decimal("0"), Decimal("0")))

    def test_amount_equals_total_is_paid(self):
        self.assertTrue(is_paid(Decimal("500"), Decimal("500")))

    def test_amount_less_than_total_is_not_paid(self):
        self.assertFalse(is_paid(Decimal("300"), Decimal("500")))

    def test_amount_greater_than_total_is_not_paid(self):
        self.assertFalse(is_paid(Decimal("600"), Decimal("500")))

    def test_amount_none_and_total_nonzero_is_not_paid(self):
        self.assertFalse(is_paid(None, Decimal("500")))

    def test_both_none_is_not_paid(self):
        self.assertFalse(is_paid(None, None))

    def test_total_none_is_not_paid_regardless_of_amount(self):
        self.assertFalse(is_paid(Decimal("500"), None))


class LoadSheetIdTests(SimpleTestCase):
    def test_valid_json_returns_sheet_id(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"sheet_id": "1AbCxyz"}, f)
            path = f.name

        try:
            self.assertEqual(load_sheet_id(path), "1AbCxyz")
        finally:
            Path(path).unlink()

    def test_missing_sheet_id_key_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"wrong_key": "1AbCxyz"}, f)
            path = f.name

        try:
            with self.assertRaises(ValueError):
                load_sheet_id(path)
        finally:
            Path(path).unlink()

    def test_empty_sheet_id_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump({"sheet_id": ""}, f)
            path = f.name

        try:
            with self.assertRaises(ValueError):
                load_sheet_id(path)
        finally:
            Path(path).unlink()

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_sheet_id("does-not-exist.json")

    def test_invalid_json_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            f.write("{invalid json")
            path = f.name

        try:
            with self.assertRaises(json.JSONDecodeError):
                load_sheet_id(path)
        finally:
            Path(path).unlink()


class GetSheetRowsTests(SimpleTestCase):
    @patch("main.management.commands.sync_sheet.gspread")
    @patch("main.management.commands.sync_sheet.service_account")
    @patch("main.management.commands.sync_sheet.load_sheet_id")
    def test_get_sheet_rows_returns_records(
        self,
        mock_load_sheet_id,
        mock_service_account,
        mock_gspread,
    ):
        mock_load_sheet_id.return_value = "sheet-id"

        mock_credentials = MagicMock()
        mock_service_account.Credentials.from_service_account_file.return_value = (
            mock_credentials
        )

        mock_client = MagicMock()
        mock_gspread.authorize.return_value = mock_client

        mock_sheet = MagicMock()
        mock_worksheet = MagicMock()

        mock_client.open_by_key.return_value = mock_sheet
        mock_sheet.worksheet.return_value = mock_worksheet
        mock_worksheet.get_all_records.return_value = [{"SUTARTIES NR.": "A-001"}]

        with patch.dict(
            "os.environ",
            {
                "GOOGLE_SHEETS_CREDENTIALS_PATH": "credentials.json",
                "GOOGLE_SHEET_ID_PATH": "sheet_id.json",
            },
        ):
            result = get_sheet_rows()

        self.assertEqual(result, [{"SUTARTIES NR.": "A-001"}])

        mock_load_sheet_id.assert_called_once_with("sheet_id.json")
        mock_service_account.Credentials.from_service_account_file.assert_called_once()
        mock_gspread.authorize.assert_called_once_with(mock_credentials)
        mock_client.open_by_key.assert_called_once_with("sheet-id")
        mock_sheet.worksheet.assert_called_once_with("Sheet1")
        mock_worksheet.get_all_records.assert_called_once_with(head=6)


class SyncSheetCommandTests(TestCase):
    def setUp(self):
        self.command = Command()

    def make_row(
        self,
        contract_number="CON-001",
        client_name="Test Client",
        payment_type="Avansas",
        client_total="1000",
        client_deposit="500",
        client_final="500",
        factory_amount="800",
        factory_deposit="400",
        factory_final="400",
        packaging_cost="-",
    ):
        c = SHEET_COLUMNS

        return {
            c["contract_number"]: contract_number,
            c["factory_order_number"]: "FAC-001",
            c["factory_order_amount"]: factory_amount,
            c["factory_deposit_amount"]: factory_deposit,
            c["factory_final_amount"]: factory_final,
            c["factory_packaging_cost"]: packaging_cost,
            c["client"]: client_name,
            c["client_representative"]: "John Smith",
            c["production_start_date"]: "2026.02.01",
            c["production_end_date"]: "2026.02.10",
            c["shipment_delivery_date"]: "2026.02.15",
            c["country"]: "Lithuania",
            c["client_total_amount"]: client_total,
            c["client_payment_type"]: payment_type,
            c["client_deposit_amount"]: client_deposit,
            c["client_final_amount"]: client_final,
            c["client_final_due_date"]: "2026.02.20",
            c["client_shipment_address"]: "Vilnius",
            c["client_contact"]: "+37060000000",
            c["courier"]: "DSV",
            c["shipment_cost"]: "100",
        }

    def test_sync_row_creates_all_related_objects(self):
        row = self.make_row()

        self.command._sync_row(row, "CON-001")

        client = Client.objects.get(client_name="Test Client")
        order = Order.objects.get(contract_number="CON-001")

        self.assertEqual(order.client, client)
        self.assertEqual(order.country, "Lithuania")

        client_order = ClientOrder.objects.get(order=order)

        self.assertEqual(client_order.client, client)
        self.assertEqual(client_order.total_amount, Decimal("1000"))
        self.assertEqual(client_order.payment_type, "Avansas")

        factory_order = FactoryOrder.objects.get(order=order)

        self.assertEqual(
            factory_order.factory_order_number,
            "FAC-001",
        )
        self.assertEqual(
            factory_order.order_amount,
            Decimal("800"),
        )

        transport = Transport.objects.get(order=order)

        self.assertEqual(transport.courier, "DSV")
        self.assertEqual(transport.delivery_address, "Vilnius")
        self.assertEqual(transport.delivery_price, Decimal("100"))

    def test_sync_row_requires_client_name(self):
        row = self.make_row(client_name="")

        with self.assertRaisesMessage(ValueError, "missing client name"):
            self.command._sync_row(row, "CON-001")

    def test_avansas_creates_deposit_and_final_tracking(self):
        row = self.make_row(
            payment_type="Avansas",
            client_total="1000",
            client_deposit="500",
            client_final="500",
        )

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        deposit_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_DEPOSIT)
        final_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FINAL)

        deposit = DepositClient.objects.get(
            client_order=client_order,
            deposit_type=deposit_type,
        )
        final = DepositClient.objects.get(
            client_order=client_order,
            deposit_type=final_type,
        )

        self.assertEqual(deposit.amount, Decimal("500"))
        self.assertTrue(deposit.is_paid)

        self.assertEqual(final.amount, Decimal("500"))
        self.assertTrue(final.is_paid)

    def test_avansas_creates_full_payment_when_deposit_covers_total(self):
        row = self.make_row(
            payment_type="Avansas",
            client_total="1000",
            client_deposit="1000",
            client_final="0",
        )

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        final_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FINAL)

        final = DepositClient.objects.get(
            client_order=client_order,
            deposit_type=final_type,
        )

        self.assertTrue(final.is_paid)

    def test_visa_suma_creates_full_payment(self):
        row = self.make_row(
            payment_type="Visa suma",
            client_total="1000",
            client_deposit="1000",
            client_final="0",
        )

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        full_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FULL)

        full_payment = DepositClient.objects.get(
            client_order=client_order,
            deposit_type=full_type,
        )

        self.assertEqual(full_payment.amount, Decimal("1000"))
        self.assertTrue(full_payment.is_paid)

        self.assertFalse(
            DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__type_name=DEPOSIT_TYPE_DEPOSIT,
            ).exists()
        )

        self.assertFalse(
            DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__type_name=DEPOSIT_TYPE_FINAL,
            ).exists()
        )

    def test_po_pristatymo_creates_full_payment_with_due_date(self):
        row = self.make_row(
            payment_type="Po pristatymo",
            client_total="1000",
            client_deposit="0",
            client_final="1000",
        )

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        full_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FULL)

        full_payment = DepositClient.objects.get(
            client_order=client_order,
            deposit_type=full_type,
        )

        self.assertEqual(
            full_payment.payment_due_by.isoformat(),
            "2026-02-20",
        )
        self.assertTrue(full_payment.is_paid)

    def test_empty_payment_type_clears_client_deposits_and_adds_warning(self):
        row = self.make_row(
            payment_type="",
            client_total="1000",
            client_deposit="500",
            client_final="500",
        )

        self.command._warnings = []

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        self.assertFalse(
            DepositClient.objects.filter(client_order=client_order).exists()
        )

        self.assertEqual(len(self.command._warnings), 1)
        self.assertIn(
            "no MOKĖJIMO TIPAS selected",
            self.command._warnings[0],
        )

    def test_unknown_payment_type_raises(self):
        row = self.make_row(
            payment_type="Unknown payment type",
        )

        with self.assertRaisesMessage(
            ValueError,
            "Unknown payment type",
        ):
            self.command._sync_row(row, "CON-001")

    def test_blank_client_amounts_clear_existing_deposits(self):
        row = self.make_row(
            client_total="-",
            client_deposit="-",
            client_final="-",
        )

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        self.assertFalse(
            DepositClient.objects.filter(client_order=client_order).exists()
        )

    def test_negative_client_total_clears_deposit_and_adds_warning(self):
        row = self.make_row(
            client_total="-500",
            client_deposit="100",
            client_final="400",
        )

        self.command._warnings = []

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        self.assertFalse(
            DepositClient.objects.filter(
                client_order=client_order,
                deposit_type__in=DepositType.objects.filter(
                    type_name__in=[
                        DEPOSIT_TYPE_DEPOSIT,
                        DEPOSIT_TYPE_FINAL,
                    ]
                ),
            ).exists()
        )

        self.assertEqual(len(self.command._warnings), 1)
        self.assertIn(
            "Negative client total amount",
            self.command._warnings[0],
        )

    def test_zero_total_is_paid(self):
        row = self.make_row(
            payment_type="Visa suma",
            client_total="0",
            client_deposit="0",
            client_final="0",
        )

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        full_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FULL)

        payment = DepositClient.objects.get(
            client_order=client_order,
            deposit_type=full_type,
        )

        self.assertTrue(payment.is_paid)

    def test_factory_fully_paid_marks_both_payments_paid(self):
        row = self.make_row(
            factory_amount="800",
            factory_deposit="400",
            factory_final="400",
        )

        self.command._sync_row(row, "CON-001")

        factory_order = FactoryOrder.objects.get(order__contract_number="CON-001")

        deposit_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_DEPOSIT)
        final_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FINAL)

        factory_deposit = DepositFactory.objects.get(
            factory_order=factory_order,
            deposit_type=deposit_type,
        )
        factory_final = DepositFactory.objects.get(
            factory_order=factory_order,
            deposit_type=final_type,
        )

        self.assertTrue(factory_deposit.is_paid)
        self.assertTrue(factory_final.is_paid)

    def test_factory_packaging_cost_is_included_in_paid_amount(self):
        row = self.make_row(
            factory_amount="1000",
            factory_deposit="400",
            factory_final="400",
            packaging_cost="200",
        )

        self.command._sync_row(row, "CON-001")

        factory_order = FactoryOrder.objects.get(order__contract_number="CON-001")

        deposit_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_DEPOSIT)
        final_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FINAL)

        factory_deposit = DepositFactory.objects.get(
            factory_order=factory_order,
            deposit_type=deposit_type,
        )
        factory_final = DepositFactory.objects.get(
            factory_order=factory_order,
            deposit_type=final_type,
        )

        self.assertTrue(factory_deposit.is_paid)
        self.assertTrue(factory_final.is_paid)

    def test_factory_packaging_cost_blank_is_not_included(self):
        row = self.make_row(
            factory_amount="1000",
            factory_deposit="400",
            factory_final="400",
            packaging_cost="-",
        )

        self.command._sync_row(row, "CON-001")

        factory_order = FactoryOrder.objects.get(order__contract_number="CON-001")

        deposit_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_DEPOSIT)
        final_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FINAL)

        factory_deposit = DepositFactory.objects.get(
            factory_order=factory_order,
            deposit_type=deposit_type,
        )

        self.assertFalse(factory_deposit.is_paid)

    def test_handle_aborts_when_sheet_is_empty(self):
        with patch(
            "main.management.commands.sync_sheet.get_sheet_rows",
            return_value=[],
        ):
            result = self.command.handle()

        self.assertEqual(result["status"], "aborted")
        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["duplicates"], 0)
        self.assertEqual(result["deleted"], 0)

    def test_handle_syncs_valid_rows(self):
        rows = [
            self.make_row(contract_number="CON-001"),
            self.make_row(contract_number="CON-002"),
        ]

        with patch(
            "main.management.commands.sync_sheet.get_sheet_rows",
            return_value=rows,
        ):
            result = self.command.handle()

        result = json.loads(result)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["synced"], 2)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["duplicates"], 0)

        self.assertEqual(Order.objects.count(), 2)

    def test_handle_skips_row_without_contract_number(self):
        rows = [
            self.make_row(contract_number=""),
            self.make_row(contract_number="CON-001"),
        ]

        with patch(
            "main.management.commands.sync_sheet.get_sheet_rows",
            return_value=rows,
        ):
            result = self.command.handle()

        result = json.loads(result)

        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(Order.objects.count(), 1)

    def test_handle_skips_duplicate_contract_numbers(self):
        rows = [
            self.make_row(contract_number="CON-001"),
            self.make_row(
                contract_number="CON-001",
                client_name="Different Client",
            ),
        ]

        with patch(
            "main.management.commands.sync_sheet.get_sheet_rows",
            return_value=rows,
        ):
            result = self.command.handle()

        result = json.loads(result)

        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(Order.objects.count(), 0)

    def test_handle_skips_row_when_sync_raises_exception(self):
        rows = [
            self.make_row(contract_number="CON-001"),
        ]

        with patch.object(
            self.command,
            "_sync_row",
            side_effect=ValueError("test failure"),
        ):
            with patch(
                "main.management.commands.sync_sheet.get_sheet_rows",
                return_value=rows,
            ):
                result = self.command.handle()

        result = json.loads(result)

        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("test failure", result["warnings"][0])

    def test_handle_deletes_orders_missing_from_sheet(self):
        client = Client.objects.create(client_name="Old Client")

        Order.objects.create(
            contract_number="OLD-001",
            client=client,
            country="Lithuania",
        )

        rows = [
            self.make_row(contract_number="CON-001"),
        ]

        with patch(
            "main.management.commands.sync_sheet.get_sheet_rows",
            return_value=rows,
        ):
            result = self.command.handle()

        result = json.loads(result)

        self.assertEqual(result["deleted"], 1)
        self.assertFalse(Order.objects.filter(contract_number="OLD-001").exists())
        self.assertTrue(Order.objects.filter(contract_number="CON-001").exists())

    def test_handle_keeps_duplicate_contract_data_untouched(self):
        client = Client.objects.create(client_name="Existing Client")

        Order.objects.create(
            contract_number="CON-001",
            client=client,
            country="Lithuania",
        )

        rows = [
            self.make_row(
                contract_number="CON-001",
                client_name="New Client",
            ),
            self.make_row(
                contract_number="CON-001",
                client_name="Another Client",
            ),
        ]

        with patch(
            "main.management.commands.sync_sheet.get_sheet_rows",
            return_value=rows,
        ):
            result = self.command.handle()

        result = json.loads(result)

        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["skipped"], 2)

        order = Order.objects.get(contract_number="CON-001")

        self.assertEqual(
            order.client.client_name,
            "Existing Client",
        )

    def test_handle_reports_duplicate_warning(self):
        rows = [
            self.make_row(contract_number="CON-001"),
            self.make_row(contract_number="CON-001"),
        ]

        with patch(
            "main.management.commands.sync_sheet.get_sheet_rows",
            return_value=rows,
        ):
            result = self.command.handle()

        result = json.loads(result)

        self.assertTrue(
            any(
                "duplicate contract numbers" in warning
                for warning in result["warnings"]
            )
        )

    def test_handle_returns_warnings_from_failed_rows(self):
        rows = [
            self.make_row(contract_number="CON-001"),
        ]

        with patch(
            "main.management.commands.sync_sheet.get_sheet_rows",
            return_value=rows,
        ):
            with patch.object(
                self.command,
                "_sync_row",
                side_effect=RuntimeError("database error"),
            ):
                result = self.command.handle()

        result = json.loads(result)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("database error", result["warnings"][0])

    def test_sync_row_updates_existing_order(self):
        row = self.make_row()

        self.command._sync_row(row, "CON-001")

        row[SHEET_COLUMNS["country"]] = "Germany"
        row[SHEET_COLUMNS["client_representative"]] = "Updated Person"

        self.command._sync_row(row, "CON-001")

        self.assertEqual(
            Order.objects.get(contract_number="CON-001").country,
            "Germany",
        )

        self.assertEqual(
            ClientOrder.objects.get(
                order__contract_number="CON-001"
            ).client_representative,
            "Updated Person",
        )

        self.assertEqual(Order.objects.count(), 1)

    def test_sync_row_reuses_existing_client(self):
        Client.objects.create(client_name="Test Client")

        row = self.make_row()

        self.command._sync_row(row, "CON-001")
        self.command._sync_row(row, "CON-002")

        self.assertEqual(
            Client.objects.filter(client_name="Test Client").count(),
            1,
        )

    def test_sync_row_updates_existing_deposit_records(self):
        row = self.make_row(
            payment_type="Avansas",
            client_total="1000",
            client_deposit="400",
            client_final="600",
        )

        self.command._sync_row(row, "CON-001")

        row[SHEET_COLUMNS["client_deposit_amount"]] = "500"
        row[SHEET_COLUMNS["client_final_amount"]] = "500"

        self.command._sync_row(row, "CON-001")

        client_order = ClientOrder.objects.get(order__contract_number="CON-001")

        deposit_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_DEPOSIT)
        final_type = DepositType.objects.get(type_name=DEPOSIT_TYPE_FINAL)

        deposit = DepositClient.objects.get(
            client_order=client_order,
            deposit_type=deposit_type,
        )
        final = DepositClient.objects.get(
            client_order=client_order,
            deposit_type=final_type,
        )

        self.assertEqual(deposit.amount, Decimal("500"))
        self.assertEqual(final.amount, Decimal("500"))

        self.assertEqual(
            DepositClient.objects.filter(client_order=client_order).count(),
            2,
        )

    def test_transport_values_are_updated(self):
        row = self.make_row()

        self.command._sync_row(row, "CON-001")

        row[SHEET_COLUMNS["courier"]] = "NTEX"
        row[SHEET_COLUMNS["client_shipment_address"]] = "Kaunas"
        row[SHEET_COLUMNS["shipment_cost"]] = "250"
        row[SHEET_COLUMNS["shipment_delivery_date"]] = "2026-03-01"

        self.command._sync_row(row, "CON-001")

        transport = Transport.objects.get(order__contract_number="CON-001")

        self.assertEqual(transport.courier, "NTEX")
        self.assertEqual(transport.delivery_address, "Kaunas")
        self.assertEqual(transport.delivery_price, Decimal("250"))
        self.assertEqual(
            transport.delivery_date.isoformat(),
            "2026-03-01",
        )
