"""
main/tests/test_tasks.py

Tests for main/services.py's get_due_reminders() (the DB-querying half
of services.py we haven't covered yet) and main/tasks.py's Celery tasks.
"""

from datetime import timedelta
from unittest.mock import patch, Mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from main.models import (
    Client,
    Order,
    ClientOrder,
    FactoryOrder,
    Transport,
    DepositType,
    DepositClient,
    DepositFactory,
    NtfySentReminder,
    SiteSettings,
)
from main.services import get_due_reminders
from main.tasks import check_reminders_task, sync_sheet_task, _push_ntfy


class GetDueRemindersTests(TestCase):
    def setUp(self):
        self.today = timezone.now().date()
        self.client_obj = Client.objects.create(client_name="Acme Furniture")
        self.deposit_type, _ = DepositType.objects.get_or_create(type_name="Deposit")

    def _order(self, contract_number="26KL 07-01/1"):
        return Order.objects.create(
            client=self.client_obj, contract_number=contract_number
        )

    def test_empty_when_nothing_due(self):
        # Fully paid/confirmed order, nothing should surface as due.
        order = self._order()
        client_order = ClientOrder.objects.create(order=order, client=self.client_obj)
        factory_order = FactoryOrder.objects.create(order=order)
        DepositClient.objects.create(
            client_order=client_order, deposit_type=self.deposit_type, is_paid=True
        )
        DepositFactory.objects.create(
            factory_order=factory_order, deposit_type=self.deposit_type, is_paid=True
        )
        Transport.objects.create(order=order, courier="DSV")

        due = get_due_reminders(self.today)
        self.assertEqual(due, [])

    def test_unpaid_client_deposit_within_window_is_due(self):
        order = self._order()
        client_order = ClientOrder.objects.create(order=order, client=self.client_obj)
        DepositClient.objects.create(
            client_order=client_order,
            deposit_type=self.deposit_type,
            amount=500,
            payment_due_by=self.today + timedelta(days=3),
        )
        due = get_due_reminders(self.today)
        ids = [item["id"] for item in due]
        self.assertIn(f"client-deposit-{order.id}", ids)

    def test_unpaid_deposit_beyond_7_days_is_not_yet_due(self):
        order = self._order()
        client_order = ClientOrder.objects.create(order=order, client=self.client_obj)
        DepositClient.objects.create(
            client_order=client_order,
            deposit_type=self.deposit_type,
            amount=500,
            payment_due_by=self.today + timedelta(days=20),
        )
        due = get_due_reminders(self.today)
        ids = [item["id"] for item in due]
        self.assertNotIn(f"client-deposit-{order.id}", ids)

    def test_already_reminder_sent_deposit_excluded(self):
        order = self._order()
        client_order = ClientOrder.objects.create(order=order, client=self.client_obj)
        DepositClient.objects.create(
            client_order=client_order,
            deposit_type=self.deposit_type,
            amount=500,
            payment_due_by=self.today + timedelta(days=3),
            is_reminder_sent=True,
        )
        due = get_due_reminders(self.today)
        ids = [item["id"] for item in due]
        self.assertNotIn(f"client-deposit-{order.id}", ids)

    def test_transport_pending_within_window_is_due(self):
        order = self._order()
        Transport.objects.create(
            order=order, delivery_date=self.today + timedelta(days=5)
        )
        due = get_due_reminders(self.today)
        ids = [item["id"] for item in due]
        self.assertIn(f"transport-{order.id}", ids)

    def test_confirmed_transport_never_due(self):
        order = self._order()
        Transport.objects.create(
            order=order, courier="DSV", delivery_date=self.today + timedelta(days=1)
        )
        due = get_due_reminders(self.today)
        ids = [item["id"] for item in due]
        self.assertNotIn(f"transport-{order.id}", ids)

    def test_furniture_reminder_due_when_overdue(self):
        order = self._order()
        factory_order = FactoryOrder.objects.create(
            order=order, production_start_date=self.today - timedelta(days=1)
        )
        due = get_due_reminders(self.today)
        ids = [item["id"] for item in due]
        self.assertIn(f"furniture-{factory_order.id}", ids)

    def test_furniture_reminder_not_due_when_in_future(self):
        order = self._order()
        factory_order = FactoryOrder.objects.create(
            order=order, production_start_date=self.today + timedelta(days=30)
        )
        due = get_due_reminders(self.today)
        ids = [item["id"] for item in due]
        self.assertNotIn(f"furniture-{factory_order.id}", ids)

    def test_package_reminder_due_when_overdue(self):
        order = self._order()
        factory_order = FactoryOrder.objects.create(
            order=order, production_end_date=self.today - timedelta(days=1)
        )
        due = get_due_reminders(self.today)
        ids = [item["id"] for item in due]
        self.assertIn(f"package-{factory_order.id}", ids)

    def test_message_contains_contract_number(self):
        order = self._order(contract_number="26KL 07-99/1")
        Transport.objects.create(
            order=order, delivery_date=self.today + timedelta(days=2)
        )
        due = get_due_reminders(self.today)
        transport_item = next(
            item for item in due if item["id"] == f"transport-{order.id}"
        )
        self.assertIn("26KL 07-99/1", transport_item["message"])

    def test_respects_site_language_setting(self):
        # Confirms get_due_reminders wraps its logic in
        # translation.override(SiteSettings.get_language()) — messages
        # should come back in Lithuanian when the site is set to lt.
        SiteSettings.objects.update_or_create(pk=1, defaults={"language": "lt"})
        order = self._order()
        Transport.objects.create(
            order=order, delivery_date=self.today + timedelta(days=2)
        )
        due = get_due_reminders(self.today)
        transport_item = next(
            item for item in due if item["id"] == f"transport-{order.id}"
        )
        self.assertIn("Laukiama transporto", transport_item["message"])
        # reset for other tests
        SiteSettings.objects.update_or_create(pk=1, defaults={"language": "en"})


class PushNtfyTests(TestCase):
    @patch("main.tasks.requests.post")
    def test_sends_correct_url_and_auth(self, mock_post):
        mock_post.return_value = Mock(status_code=200)
        mock_post.return_value.raise_for_status = Mock()

        _push_ntfy("Test message")

        called_url = mock_post.call_args[0][0]
        self.assertIn("ag-solutions-reminders", called_url)
        self.assertIn("auth", mock_post.call_args[1])

    @patch("main.tasks.requests.post")
    def test_raises_on_http_error(self, mock_post):
        import requests

        mock_post.return_value = Mock(status_code=401)
        mock_post.return_value.raise_for_status.side_effect = requests.HTTPError("401")

        with self.assertRaises(requests.HTTPError):
            _push_ntfy("Test message")


class CheckRemindersTaskTests(TestCase):
    def setUp(self):
        self.today = timezone.now().date()
        self.client_obj = Client.objects.create(client_name="Acme Furniture")
        self.order = Order.objects.create(
            client=self.client_obj, contract_number="26KL 07-01/1"
        )

    @patch("main.tasks._push_ntfy")
    def test_pushes_newly_due_reminder(self, mock_push):
        Transport.objects.create(
            order=self.order, delivery_date=self.today + timedelta(days=2)
        )
        result = check_reminders_task()
        self.assertEqual(result["pushed"], 1)
        self.assertTrue(mock_push.called)
        self.assertTrue(
            NtfySentReminder.objects.filter(
                reminder_id=f"transport-{self.order.id}"
            ).exists()
        )

    @patch("main.tasks._push_ntfy")
    def test_does_not_repush_within_24_hours(self, mock_push):
        Transport.objects.create(
            order=self.order, delivery_date=self.today + timedelta(days=2)
        )
        reminder_id = f"transport-{self.order.id}"
        NtfySentReminder.objects.create(
            reminder_id=reminder_id, last_sent_at=timezone.now()
        )

        result = check_reminders_task()
        self.assertEqual(result["pushed"], 0)
        mock_push.assert_not_called()

    @patch("main.tasks._push_ntfy")
    def test_repushes_after_24_hours(self, mock_push):
        Transport.objects.create(
            order=self.order, delivery_date=self.today + timedelta(days=2)
        )
        reminder_id = f"transport-{self.order.id}"
        NtfySentReminder.objects.create(
            reminder_id=reminder_id, last_sent_at=timezone.now() - timedelta(hours=25)
        )

        result = check_reminders_task()
        self.assertEqual(result["pushed"], 1)
        mock_push.assert_called_once()

    @patch("main.tasks._push_ntfy")
    def test_cleans_up_resolved_reminders(self, mock_push):
        # A tracking row exists for a reminder that's no longer due
        # (e.g. marked sent since) — should get deleted so it starts
        # fresh if it ever recurs.
        NtfySentReminder.objects.create(
            reminder_id="transport-999", last_sent_at=timezone.now()
        )
        check_reminders_task()
        self.assertFalse(
            NtfySentReminder.objects.filter(reminder_id="transport-999").exists()
        )

    @patch("main.tasks._push_ntfy")
    def test_push_failure_triggers_retry(self, mock_push):
        import requests

        mock_push.side_effect = requests.HTTPError("401 Unauthorized")
        Transport.objects.create(
            order=self.order, delivery_date=self.today + timedelta(days=2)
        )

        with self.assertRaises(Exception):
            # Celery's self.retry() raises a Retry exception when called
            # outside a real worker context, which is expected here.
            check_reminders_task()


class SyncSheetTaskTests(TestCase):
    @patch("main.tasks.call_command")
    def test_calls_sync_sheet_management_command(self, mock_call_command):
        mock_call_command.return_value = '{"status": "success", "synced": 5}'
        result = sync_sheet_task()
        self.assertEqual(result["synced"], 5)
        mock_call_command.assert_called_once_with("sync_sheet")

    @patch("main.tasks.call_command")
    def test_handles_none_result(self, mock_call_command):
        mock_call_command.return_value = None
        result = sync_sheet_task()
        self.assertIsNone(result)

    @patch("main.tasks.call_command")
    def test_exception_triggers_retry(self, mock_call_command):
        mock_call_command.side_effect = Exception("sheet unreachable")
        with self.assertRaises(Exception):
            sync_sheet_task()
