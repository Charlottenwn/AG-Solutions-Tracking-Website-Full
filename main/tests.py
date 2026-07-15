from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase

from main.views import (
    _compute_deposit_status,
    _compute_furniture_status,
    _compute_package_clarification_status,
    _compute_transport_status,
)


def make_deposit(deposit_type_name, is_paid=False, payment_due_by=None,
                  amount=None, is_reminder_sent=False):
    """
    Lightweight stand-in for a DepositClient/DepositFactory row, avoiding
    real DB objects since _compute_deposit_status only reads attributes.
    """
    return SimpleNamespace(
        deposit_type=SimpleNamespace(type_name=deposit_type_name),
        is_paid=is_paid,
        payment_due_by=payment_due_by,
        amount=amount,
        is_reminder_sent=is_reminder_sent,
    )


def make_factory_order(furniture_reminder_date=None, is_furniture_reminder_sent=False,
                        package_clarification_reminder_date=None,
                        is_package_clarification_reminder_sent=False):
    return SimpleNamespace(
        furniture_reminder_date=furniture_reminder_date,
        is_furniture_reminder_sent=is_furniture_reminder_sent,
        package_clarification_reminder_date=package_clarification_reminder_date,
        is_package_clarification_reminder_sent=is_package_clarification_reminder_sent,
    )


def make_transport(courier="", delivery_date=None, is_reminder_sent=False):
    return SimpleNamespace(
        courier=courier,
        delivery_date=delivery_date,
        is_reminder_sent=is_reminder_sent,
    )


class ComputeDepositStatusTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 13)

    def test_no_deposits_returns_no_info(self):
        result = _compute_deposit_status([], self.today)
        self.assertEqual(result["token"], "due")
        self.assertEqual(result["label"], "no deposit info")
        self.assertFalse(result["paid"])

    def test_all_paid_returns_paid(self):
        deposits = [
            make_deposit("Deposit", is_paid=True),
            make_deposit("Final Payment", is_paid=True),
        ]
        result = _compute_deposit_status(deposits, self.today)
        self.assertTrue(result["paid"])
        self.assertEqual(result["token"], "paid")

    def test_unpaid_with_no_amount_and_no_due_date_is_no_info(self):
        # Regression: sync creates placeholder DepositFactory rows with no
        # amount and no due date before any sheet data exists. These must
        # not be treated as a real outstanding deposit (edge case #16).
        deposits = [
            make_deposit("Deposit", is_paid=False, amount=None, payment_due_by=None),
            make_deposit("Final Payment", is_paid=False, amount=None, payment_due_by=None),
        ]
        result = _compute_deposit_status(deposits, self.today)
        self.assertEqual(result["label"], "no deposit info")

    def test_unpaid_with_zero_amount_is_informative(self):
        # A row with amount=0 (explicitly entered) should NOT be treated
        # the same as amount=None (never entered).
        deposits = [
            make_deposit("Final Payment", is_paid=False, amount=Decimal("0"), payment_due_by=None),
        ]
        result = _compute_deposit_status(deposits, self.today)
        self.assertEqual(result["label"], "Final Payment due")

    def test_prefers_dated_unpaid_over_undated_unpaid(self):
        # Avansas (no due date) unpaid + Final Payment (dated) unpaid ->
        # the dated one should win and drive overdue/days_remaining, since
        # avansas is intentionally untracked (per user decision).
        deposits = [
            make_deposit("Deposit", is_paid=False, amount=Decimal("100"), payment_due_by=None),
            make_deposit(
                "Final Payment", is_paid=False, amount=Decimal("500"),
                payment_due_by=self.today - timedelta(days=5),
            ),
        ]
        result = _compute_deposit_status(deposits, self.today)
        self.assertEqual(result["deposit_type"], "Final Payment")
        self.assertTrue(result["overdue"])

    def test_falls_back_to_undated_when_nothing_dated(self):
        deposits = [
            make_deposit("Deposit", is_paid=False, amount=Decimal("100"), payment_due_by=None),
        ]
        result = _compute_deposit_status(deposits, self.today)
        self.assertEqual(result["deposit_type"], "Deposit")
        self.assertIsNone(result["days_remaining"])

    def test_due_today_is_not_yet_overdue_for_deposits(self):
        # Deposit/factory payments use a strict `< 0` boundary — due
        # exactly today is still shown as "due", not "overdue". This
        # differs intentionally from furniture/package reminders, which
        # use `<= 0` (see ComputeFurnitureStatusTests boundary test).
        deposits = [
            make_deposit(
                "Final Payment", is_paid=False, amount=Decimal("100"),
                payment_due_by=self.today,
            ),
        ]
        result = _compute_deposit_status(deposits, self.today)
        self.assertEqual(result["days_remaining"], 0)
        self.assertFalse(result["overdue"])
        self.assertEqual(result["token"], "due")

    def test_overdue_boundary_one_day_past(self):
        deposits = [
            make_deposit(
                "Final Payment", is_paid=False, amount=Decimal("100"),
                payment_due_by=self.today - timedelta(days=1),
            ),
        ]
        result = _compute_deposit_status(deposits, self.today)
        self.assertTrue(result["overdue"])
        self.assertEqual(result["token"], "overdue")


class ComputeFurnitureStatusTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 13)

    def test_no_factory_order_returns_none(self):
        self.assertIsNone(_compute_furniture_status(None, self.today))

    def test_no_reminder_date_returns_none(self):
        fo = make_factory_order(furniture_reminder_date=None)
        self.assertIsNone(_compute_furniture_status(fo, self.today))

    def test_overdue_shows_red_token_not_negative_days(self):
        fo = make_factory_order(furniture_reminder_date=self.today - timedelta(days=3))
        result = _compute_furniture_status(fo, self.today)
        self.assertEqual(result["token"], "overdue")
        self.assertIn("overdue by 3 days", result["label"])
        self.assertNotIn("-3", result["label"])

    def test_due_today_is_overdue_boundary(self):
        fo = make_factory_order(furniture_reminder_date=self.today)
        result = _compute_furniture_status(fo, self.today)
        self.assertEqual(result["token"], "overdue")
        self.assertTrue(result["due"])

    def test_future_date_shows_amber_due(self):
        fo = make_factory_order(furniture_reminder_date=self.today + timedelta(days=5))
        result = _compute_furniture_status(fo, self.today)
        self.assertEqual(result["token"], "due")
        self.assertIn("in 5 days", result["label"])

    def test_sent_reminder_shows_paid_token_regardless_of_date(self):
        fo = make_factory_order(
            furniture_reminder_date=self.today - timedelta(days=10),
            is_furniture_reminder_sent=True,
        )
        result = _compute_furniture_status(fo, self.today)
        self.assertEqual(result["token"], "paid")
        self.assertEqual(result["label"], "Furniture reminder sent")

    def test_due_key_present_for_stat_counting(self):
        # Regression: this key was renamed to "overdue" multiple times
        # during development, breaking the stat-card sum in views.py.
        fo = make_factory_order(furniture_reminder_date=self.today - timedelta(days=1))
        result = _compute_furniture_status(fo, self.today)
        self.assertIn("due", result)
        self.assertTrue(result["due"])


class ComputePackageClarificationStatusTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 13)

    def test_no_reminder_date_returns_none(self):
        fo = make_factory_order(package_clarification_reminder_date=None)
        self.assertIsNone(_compute_package_clarification_status(fo, self.today))

    def test_overdue_shows_red_token(self):
        fo = make_factory_order(
            package_clarification_reminder_date=self.today - timedelta(days=12)
        )
        result = _compute_package_clarification_status(fo, self.today)
        self.assertEqual(result["token"], "overdue")
        self.assertIn("overdue by 12 days", result["label"])

    def test_sent_reminder_shows_paid_token(self):
        fo = make_factory_order(
            package_clarification_reminder_date=self.today - timedelta(days=12),
            is_package_clarification_reminder_sent=True,
        )
        result = _compute_package_clarification_status(fo, self.today)
        self.assertEqual(result["token"], "paid")

    def test_due_key_present_for_stat_counting(self):
        fo = make_factory_order(
            package_clarification_reminder_date=self.today + timedelta(days=1)
        )
        result = _compute_package_clarification_status(fo, self.today)
        self.assertIn("due", result)
        self.assertFalse(result["due"])


class ComputeTransportStatusTests(TestCase):
    def setUp(self):
        self.today = date(2026, 7, 13)

    def test_no_transport_returns_pending(self):
        result = _compute_transport_status(None, self.today)
        self.assertEqual(result["token"], "pending")

    def test_no_courier_no_date_is_pending(self):
        transport = make_transport(courier="", delivery_date=None)
        result = _compute_transport_status(transport, self.today)
        self.assertEqual(result["token"], "pending")
        self.assertEqual(result["label"], "Transport pending")

    def test_no_courier_overdue_date_is_overdue(self):
        transport = make_transport(
            courier="", delivery_date=self.today - timedelta(days=4)
        )
        result = _compute_transport_status(transport, self.today)
        self.assertEqual(result["token"], "overdue")
        self.assertTrue(result["overdue"])

    def test_courier_confirmed_even_if_date_passed(self):
        # Edge case #15: once a courier is assigned, status is "confirmed"
        # (green), not "overdue" — but the label should still mention
        # lateness rather than silently hiding it.
        transport = make_transport(
            courier="DSV", delivery_date=self.today - timedelta(days=3)
        )
        result = _compute_transport_status(transport, self.today)
        self.assertEqual(result["token"], "confirmed")
        self.assertFalse(result["overdue"])
        self.assertIn("past original date", result["label"])

    def test_courier_confirmed_future_date_plain_label(self):
        transport = make_transport(
            courier="DSV", delivery_date=self.today + timedelta(days=3)
        )
        result = _compute_transport_status(transport, self.today)
        self.assertEqual(result["label"], "Transport confirmed")

# Create your tests here.
