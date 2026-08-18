"""
main/tests_models.py

Sanity tests for main/models.py — save()-time calculated fields,
defaults, and the SiteSettings singleton pattern. Uses TestCase since
these need a real (test) database.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from main.models import (
    Client,
    Order,
    Transport,
    FactoryOrder,
    DepositType,
    DepositClient,
    DepositFactory,
    SiteSettings,
)


class ClientModelTests(TestCase):
    def test_str_returns_client_name(self):
        client = Client.objects.create(client_name="Acme Furniture")
        self.assertEqual(str(client), "Acme Furniture")

    def test_contact_number_blank_by_default(self):
        client = Client.objects.create(client_name="Acme Furniture")
        self.assertEqual(client.client_contact_number, "")


class OrderModelTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(client_name="Acme Furniture")

    def test_str_returns_contract_number(self):
        order = Order.objects.create(
            client=self.client_obj, contract_number="26KL 07-03/1"
        )
        self.assertEqual(str(order), "26KL 07-03/1")

    def test_contract_number_must_be_unique(self):
        Order.objects.create(client=self.client_obj, contract_number="26KL 07-03/1")
        with self.assertRaises(Exception):
            Order.objects.create(client=self.client_obj, contract_number="26KL 07-03/1")

    def test_default_status_is_pending(self):
        order = Order.objects.create(
            client=self.client_obj, contract_number="26KL 07-03/1"
        )
        self.assertEqual(order.status, "pending")

    def test_client_deletion_is_protected(self):
        # client uses on_delete=PROTECT — deleting a Client with orders
        # attached should raise, not cascade-delete the order.
        Order.objects.create(client=self.client_obj, contract_number="26KL 07-03/1")
        with self.assertRaises(Exception):
            self.client_obj.delete()


class TransportModelTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(client_name="Acme Furniture")
        self.order = Order.objects.create(
            client=self.client_obj, contract_number="26KL 07-03/1"
        )

    def test_reminder_date_set_far_before_delivery(self):
        # REMINDER_DAYS_BEFORE = 7 — delivery 30 days out should set
        # reminder_date to exactly 7 days before delivery.
        delivery = timezone.now().date() + timedelta(days=30)
        transport = Transport.objects.create(order=self.order, delivery_date=delivery)
        self.assertEqual(transport.reminder_date, delivery - timedelta(days=7))

    def test_reminder_date_set_to_today_when_within_window(self):
        # Delivery only 3 days out — already inside the 7-day reminder
        # window, so reminder_date should be today, not a future date.
        delivery = timezone.now().date() + timedelta(days=3)
        transport = Transport.objects.create(order=self.order, delivery_date=delivery)
        self.assertEqual(transport.reminder_date, timezone.now().date())

    def test_no_delivery_date_leaves_reminder_date_null(self):
        transport = Transport.objects.create(order=self.order)
        self.assertIsNone(transport.reminder_date)

    def test_str_representation(self):
        transport = Transport.objects.create(order=self.order)
        self.assertIn(self.order.contract_number, str(transport))


class FactoryOrderModelTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(client_name="Acme Furniture")
        self.order = Order.objects.create(
            client=self.client_obj, contract_number="26KL 07-03/1"
        )

    def test_furniture_reminder_date_is_3_days_before_production_start(self):
        start = date(2026, 9, 1)
        fo = FactoryOrder.objects.create(order=self.order, production_start_date=start)
        self.assertEqual(fo.furniture_reminder_date, date(2026, 8, 29))

    def test_package_clarification_reminder_equals_production_end(self):
        end = date(2026, 9, 15)
        fo = FactoryOrder.objects.create(order=self.order, production_end_date=end)
        self.assertEqual(fo.package_clarification_reminder_date, end)

    def test_no_production_dates_leave_reminder_dates_null(self):
        fo = FactoryOrder.objects.create(order=self.order)
        self.assertIsNone(fo.furniture_reminder_date)
        self.assertIsNone(fo.package_clarification_reminder_date)

    def test_updating_production_start_date_recalculates_reminder(self):
        fo = FactoryOrder.objects.create(
            order=self.order, production_start_date=date(2026, 9, 1)
        )
        fo.production_start_date = date(2026, 10, 1)
        fo.save()
        self.assertEqual(fo.furniture_reminder_date, date(2026, 9, 28))


class DepositModelTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(client_name="Acme Furniture")
        self.order = Order.objects.create(
            client=self.client_obj, contract_number="26KL 07-03/1"
        )
        self.deposit_type = DepositType.objects.create(type_name="Deposit")

    def test_deposit_type_str(self):
        self.assertEqual(str(self.deposit_type), "Deposit")

    def test_deposit_type_name_unique(self):
        with self.assertRaises(Exception):
            DepositType.objects.create(type_name="Deposit")

    def test_client_deposit_reminder_date_calculated_from_due_date(self):
        from main.models import ClientOrder

        client_order = ClientOrder.objects.create(
            order=self.order, client=self.client_obj
        )
        due = timezone.now().date() + timedelta(days=20)
        deposit = DepositClient.objects.create(
            client_order=client_order,
            deposit_type=self.deposit_type,
            payment_due_by=due,
        )
        self.assertEqual(deposit.reminder_date, due - timedelta(days=7))

    def test_factory_deposit_reminder_date_calculated_from_due_date(self):
        factory_order = FactoryOrder.objects.create(order=self.order)
        due = timezone.now().date() + timedelta(days=20)
        deposit = DepositFactory.objects.create(
            factory_order=factory_order,
            deposit_type=self.deposit_type,
            payment_due_by=due,
        )
        self.assertEqual(deposit.reminder_date, due - timedelta(days=7))

    def test_deposit_defaults_to_unpaid_and_no_reminder_sent(self):
        factory_order = FactoryOrder.objects.create(order=self.order)
        deposit = DepositFactory.objects.create(
            factory_order=factory_order, deposit_type=self.deposit_type
        )
        self.assertFalse(deposit.is_paid)
        self.assertFalse(deposit.is_reminder_sent)


class SiteSettingsModelTests(TestCase):
    def test_get_language_creates_default_row_if_none_exists(self):
        self.assertEqual(SiteSettings.objects.count(), 0)
        language = SiteSettings.get_language()
        self.assertEqual(language, "en")
        self.assertEqual(SiteSettings.objects.count(), 1)

    def test_save_always_forces_singleton_pk(self):
        # Even if someone tries to create a second row, save() should
        # force pk=1, meaning it overwrites the existing row rather than
        # creating a duplicate.
        SiteSettings.objects.create(language="en")
        second = SiteSettings(language="lt")
        second.save()
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(SiteSettings.objects.first().language, "lt")

    def test_get_language_returns_updated_value(self):
        SiteSettings.objects.update_or_create(pk=1, defaults={"language": "lt"})
        self.assertEqual(SiteSettings.get_language(), "lt")
