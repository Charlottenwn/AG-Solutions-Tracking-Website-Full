from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from main.services import (
    compute_deposit_status,
    compute_transport_status,
    compute_furniture_status,
    compute_package_clarification_status,
    is_order_complete,
    extract_contract_date,
    get_client_ip,
)


def make_deposit(
    *,
    is_paid=False,
    type_name="Deposit",
    amount=None,
    payment_due_by=None,
    is_reminder_sent=False
):
    """Lightweight stand-in for a DepositClient/DepositFactory row."""
    return SimpleNamespace(
        is_paid=is_paid,
        deposit_type=SimpleNamespace(type_name=type_name),
        amount=amount,
        payment_due_by=payment_due_by,
        is_reminder_sent=is_reminder_sent,
    )


def make_transport(*, courier="", delivery_date=None, is_reminder_sent=False):
    """Lightweight stand-in for a Transport row."""
    return SimpleNamespace(
        courier=courier,
        delivery_date=delivery_date,
        is_reminder_sent=is_reminder_sent,
    )


def make_factory_order(
    *,
    furniture_reminder_date=None,
    is_furniture_reminder_sent=False,
    package_clarification_reminder_date=None,
    is_package_clarification_reminder_sent=False
):
    """Lightweight stand-in for a FactoryOrder row."""
    return SimpleNamespace(
        furniture_reminder_date=furniture_reminder_date,
        is_furniture_reminder_sent=is_furniture_reminder_sent,
        package_clarification_reminder_date=package_clarification_reminder_date,
        is_package_clarification_reminder_sent=is_package_clarification_reminder_sent,
    )


class ComputeDepositStatusTests(SimpleTestCase):
    def setUp(self):
        self.today = date(2026, 8, 17)

    def test_no_deposits_returns_no_info(self):
        result = compute_deposit_status([], self.today)
        self.assertEqual(result["token"], "due")
        self.assertFalse(result["paid"])
        self.assertIsNone(result["days_remaining"])

    def test_all_paid_returns_paid(self):
        deposits = [
            make_deposit(is_paid=True, type_name="Deposit"),
            make_deposit(is_paid=True, type_name="Final Payment"),
        ]
        result = compute_deposit_status(deposits, self.today)
        self.assertEqual(result["token"], "paid")
        self.assertTrue(result["paid"])

    def test_unpaid_with_no_amount_or_due_date_is_uninformative(self):
        # A placeholder row with nothing filled in yet shouldn't produce a
        # false "due" badge — matches the sync_sheet behavior of creating
        # empty factory deposit rows before sheet data exists.
        deposits = [make_deposit(is_paid=False, amount=None, payment_due_by=None)]
        result = compute_deposit_status(deposits, self.today)
        self.assertEqual(result["token"], "due")
        self.assertIsNone(result["deposit_type"])

    def test_unpaid_with_amount_but_no_due_date(self):
        deposits = [make_deposit(is_paid=False, amount=500, payment_due_by=None)]
        result = compute_deposit_status(deposits, self.today)
        self.assertEqual(result["token"], "due")
        self.assertIsNotNone(result["deposit_type"])
        self.assertIsNone(result["days_remaining"])

    def test_unpaid_due_in_future_is_not_overdue(self):
        deposits = [
            make_deposit(
                is_paid=False, amount=500, payment_due_by=self.today + timedelta(days=5)
            )
        ]
        result = compute_deposit_status(deposits, self.today)
        self.assertEqual(result["token"], "due")
        self.assertFalse(result["overdue"])
        self.assertEqual(result["days_remaining"], 5)

    def test_unpaid_past_due_date_is_overdue(self):
        deposits = [
            make_deposit(
                is_paid=False, amount=500, payment_due_by=self.today - timedelta(days=3)
            )
        ]
        result = compute_deposit_status(deposits, self.today)
        self.assertEqual(result["token"], "overdue")
        self.assertTrue(result["overdue"])
        self.assertEqual(result["days_remaining"], -3)

    def test_deposit_priority_orders_deposit_before_final_payment(self):
        # Both unpaid — Deposit should be picked first per DEPOSIT_TYPE_PRIORITY,
        # even though Final Payment is listed first in the list.
        deposits = [
            make_deposit(
                is_paid=False,
                type_name="Final Payment",
                amount=1000,
                payment_due_by=self.today + timedelta(days=10),
            ),
            make_deposit(
                is_paid=False,
                type_name="Deposit",
                amount=500,
                payment_due_by=self.today + timedelta(days=2),
            ),
        ]
        result = compute_deposit_status(deposits, self.today)
        self.assertEqual(result["deposit_type"], "Deposit")

    def test_reminder_sent_flag_passes_through(self):
        deposits = [
            make_deposit(
                is_paid=False,
                amount=500,
                payment_due_by=self.today - timedelta(days=1),
                is_reminder_sent=True,
            )
        ]
        result = compute_deposit_status(deposits, self.today)
        self.assertTrue(result["reminder_sent"])


class ComputeTransportStatusTests(SimpleTestCase):
    def setUp(self):
        self.today = date(2026, 8, 17)

    def test_no_transport_row_is_pending(self):
        result = compute_transport_status(None, self.today)
        self.assertEqual(result["token"], "pending")
        self.assertIsNone(result["days_remaining"])

    def test_no_courier_no_date_is_pending(self):
        result = compute_transport_status(make_transport(), self.today)
        self.assertEqual(result["token"], "pending")

    def test_courier_assigned_is_confirmed(self):
        result = compute_transport_status(make_transport(courier="DSV"), self.today)
        self.assertEqual(result["token"], "confirmed")
        self.assertEqual(result["courier"], "DSV")

    def test_no_courier_future_date_shows_days_remaining(self):
        result = compute_transport_status(
            make_transport(delivery_date=self.today + timedelta(days=7)), self.today
        )
        self.assertEqual(result["token"], "pending")
        self.assertEqual(result["days_remaining"], 7)
        self.assertFalse(result["overdue"])

    def test_no_courier_past_date_is_overdue(self):
        result = compute_transport_status(
            make_transport(delivery_date=self.today - timedelta(days=2)), self.today
        )
        self.assertEqual(result["token"], "overdue")
        self.assertTrue(result["overdue"])

    def test_courier_assigned_past_original_date_still_confirmed(self):
        # Confirmed transport overrides overdue — courier being set means
        # it shipped, even if the original planned date has passed.
        result = compute_transport_status(
            make_transport(
                courier="NTEX", delivery_date=self.today - timedelta(days=5)
            ),
            self.today,
        )
        self.assertEqual(result["token"], "confirmed")
        self.assertFalse(result["overdue"])
        self.assertIn("overdue by 5 days", result["label"])


class ComputeFurnitureStatusTests(SimpleTestCase):
    def setUp(self):
        self.today = date(2026, 8, 17)

    def test_no_factory_order_returns_none(self):
        self.assertIsNone(compute_furniture_status(None, self.today))

    def test_no_reminder_date_returns_none(self):
        fo = make_factory_order(furniture_reminder_date=None)
        self.assertIsNone(compute_furniture_status(fo, self.today))

    def test_reminder_sent_shows_sent_token(self):
        fo = make_factory_order(
            furniture_reminder_date=self.today - timedelta(days=1),
            is_furniture_reminder_sent=True,
        )
        result = compute_furniture_status(fo, self.today)
        self.assertEqual(result["token"], "paid")
        self.assertTrue(result["reminder_sent"])

    def test_reminder_date_today_counts_as_due(self):
        fo = make_factory_order(furniture_reminder_date=self.today)
        result = compute_furniture_status(fo, self.today)
        self.assertTrue(result["due"])
        self.assertEqual(result["token"], "overdue")

    def test_reminder_date_in_future_is_not_yet_due(self):
        fo = make_factory_order(furniture_reminder_date=self.today + timedelta(days=3))
        result = compute_furniture_status(fo, self.today)
        self.assertFalse(result["due"])
        self.assertEqual(result["token"], "due")
        self.assertEqual(result["days_remaining"], 3)


class ComputePackageClarificationStatusTests(SimpleTestCase):
    def setUp(self):
        self.today = date(2026, 8, 17)

    def test_no_factory_order_returns_none(self):
        self.assertIsNone(compute_package_clarification_status(None, self.today))

    def test_overdue_when_past_date_and_not_sent(self):
        fo = make_factory_order(
            package_clarification_reminder_date=self.today - timedelta(days=10)
        )
        result = compute_package_clarification_status(fo, self.today)
        self.assertEqual(result["token"], "overdue")
        self.assertTrue(result["due"])


class IsOrderCompleteTests(SimpleTestCase):
    def _statuses(
        self,
        *,
        client_paid=True,
        factory_paid=True,
        transport_token="confirmed",
        furniture=None,
        package=None
    ):
        return (
            {"paid": client_paid},
            {"paid": factory_paid},
            {"token": transport_token},
            furniture,
            package,
        )

    def test_fully_complete_order(self):
        client, factory, transport, furniture, package = self._statuses()
        self.assertTrue(
            is_order_complete(client, factory, transport, furniture, package)
        )

    def test_unpaid_client_deposit_blocks_completion(self):
        client, factory, transport, furniture, package = self._statuses(
            client_paid=False
        )
        self.assertFalse(
            is_order_complete(client, factory, transport, furniture, package)
        )

    def test_transport_not_confirmed_blocks_completion(self):
        client, factory, transport, furniture, package = self._statuses(
            transport_token="pending"
        )
        self.assertFalse(
            is_order_complete(client, factory, transport, furniture, package)
        )

    def test_furniture_reminder_not_sent_blocks_completion(self):
        client, factory, transport, _, package = self._statuses()
        furniture = {"reminder_sent": False}
        self.assertFalse(
            is_order_complete(client, factory, transport, furniture, package)
        )

    def test_furniture_reminder_sent_does_not_block(self):
        client, factory, transport, _, package = self._statuses()
        furniture = {"reminder_sent": True}
        self.assertTrue(
            is_order_complete(client, factory, transport, furniture, package)
        )

    def test_furniture_none_does_not_block(self):
        # No furniture_reminder_date on the order at all (compute_furniture_status
        # returned None) — should be treated as "nothing to wait on", not blocking.
        client, factory, transport, furniture, package = self._statuses(furniture=None)
        self.assertTrue(
            is_order_complete(client, factory, transport, furniture, package)
        )


class GetClientIpTests(SimpleTestCase):
    def test_uses_x_forwarded_for_when_present(self):
        request = Mock()
        request.META = {"HTTP_X_FORWARDED_FOR": "203.0.113.5, 10.0.0.1"}
        self.assertEqual(get_client_ip(request), "203.0.113.5")

    def test_falls_back_to_remote_addr(self):
        request = Mock()
        request.META = {"REMOTE_ADDR": "192.168.1.50"}
        self.assertEqual(get_client_ip(request), "192.168.1.50")


class ExtractContractDateTests(SimpleTestCase):
    def test_valid_contract_number_extracts_date(self):
        result = extract_contract_date("26KL 07-03/1")
        self.assertEqual(result, date(2026, 7, 3))

    def test_no_match_returns_none(self):
        result = extract_contract_date("not-a-contract-number")
        self.assertIsNone(result)

    def test_invalid_date_components_return_none(self):
        # e.g. month 13 — matches the pattern shape but isn't a real date
        result = extract_contract_date("26KL 13-99/1")
        self.assertIsNone(result)
