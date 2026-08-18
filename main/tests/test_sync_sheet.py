"""
main/tests/test_sync_sheet.py

Tests for main/management/commands/sync_sheet.py's parsing helpers —
parse_decimal, parse_date, is_paid, load_sheet_id. These handle
real-world messy spreadsheet input, so edge cases matter a lot here.
"""

import json
import tempfile
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from main.management.commands.sync_sheet import (
    parse_decimal,
    parse_date,
    is_paid,
    load_sheet_id,
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
        self.assertEqual(parse_decimal("  4,176.00  €  "), Decimal("4176.00"))

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

    def test_unrecognized_format_returns_none(self):
        self.assertIsNone(parse_date("not-a-date"))

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

    def test_amount_none_and_total_nonzero_is_not_paid(self):
        self.assertFalse(is_paid(None, Decimal("500")))

    def test_both_none_is_not_paid(self):
        self.assertFalse(is_paid(None, None))

    def test_total_none_is_not_paid_regardless_of_amount(self):
        # Can't determine "paid" without knowing the total.
        self.assertFalse(is_paid(Decimal("500"), None))


class LoadSheetIdTests(SimpleTestCase):
    def test_valid_json_returns_sheet_id(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"sheet_id": "1AbCxyz"}, f)
            path = f.name
        try:
            self.assertEqual(load_sheet_id(path), "1AbCxyz")
        finally:
            Path(path).unlink()

    def test_missing_sheet_id_key_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"wrong_key": "1AbCxyz"}, f)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_sheet_id(path)
        finally:
            Path(path).unlink()

    def test_empty_sheet_id_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"sheet_id": ""}, f)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_sheet_id(path)
        finally:
            Path(path).unlink()
