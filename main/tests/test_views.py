"""
main/tests/test_views.py

Integration tests for main/views.py — login, logout, recovery flow,
main_offer_page, reminder-marking endpoints, and the language toggle.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from main.models import (
    Client,
    Order,
    Transport,
    FactoryOrder,
    RecoverySession,
    RecoveryCode,
    UserProfile,
    SiteSettings,
)
from main.constants import RESET_TOKEN_SALT


class LoginViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mz", password="correct-password-123"
        )

    def test_get_renders_login_page(self):
        response = self.client.get(reverse("login_page"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "main/login_page.html")

    def test_correct_credentials_redirect_to_main_offer_page(self):
        response = self.client.post(
            reverse("login_page"),
            {
                "username": "mz",
                "password": "correct-password-123",
            },
        )
        self.assertRedirects(response, reverse("main_offer_page"))

    def test_wrong_password_shows_error_and_does_not_log_in(self):
        response = self.client.post(
            reverse("login_page"),
            {
                "username": "mz",
                "password": "wrong-password",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_nonexistent_user_shows_same_generic_error(self):
        # Important: don't leak whether a username exists via a different
        # error message — should be identical to the wrong-password case.
        response = self.client.post(
            reverse("login_page"),
            {
                "username": "doesnotexist",
                "password": "whatever",
            },
        )
        self.assertContains(response, "Invalid username or password")


class LogoutViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="pass123456789")

    def test_logout_redirects_to_login(self):
        self.client.login(username="mz", password="pass123456789")
        response = self.client.get(reverse("logout_view"))
        self.assertRedirects(response, reverse("login_page"))

    def test_logout_actually_ends_the_session(self):
        # This is the important one — catches the bug where logout_view
        # redirects without calling django.contrib.auth.logout().
        self.client.login(username="mz", password="pass123456789")
        self.client.get(reverse("logout_view"))
        response = self.client.get(reverse("main_offer_page"))
        # Should redirect to login (i.e. NOT be authenticated anymore)
        self.assertRedirects(
            response, f"{reverse('login_page')}?next={reverse('main_offer_page')}"
        )


class MainOfferPageAccessTests(TestCase):
    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("main_offer_page"))
        self.assertRedirects(
            response, f"{reverse('login_page')}?next={reverse('main_offer_page')}"
        )

    def test_authenticated_user_can_access(self):
        User.objects.create_user(username="mz", password="pass123456789")
        self.client.login(username="mz", password="pass123456789")
        response = self.client.get(reverse("main_offer_page"))
        self.assertEqual(response.status_code, 200)


class MainOfferPageContentTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="mz", password="pass123456789")
        self.client.login(username="mz", password="pass123456789")
        self.client_obj = Client.objects.create(client_name="Acme Furniture")

    def _make_complete_order(self, contract_number="26KL 07-01/1"):
        """
        Builds an order that satisfies is_order_complete: both deposits
        paid, transport confirmed, no furniture/package reminders pending.
        """
        from main.models import ClientOrder, DepositType, DepositClient, DepositFactory

        order = Order.objects.create(
            client=self.client_obj, contract_number=contract_number
        )
        client_order = ClientOrder.objects.create(order=order, client=self.client_obj)
        factory_order = FactoryOrder.objects.create(order=order)
        deposit_type, _ = DepositType.objects.get_or_create(type_name="Deposit")
        DepositClient.objects.create(
            client_order=client_order, deposit_type=deposit_type, is_paid=True
        )
        DepositFactory.objects.create(
            factory_order=factory_order, deposit_type=deposit_type, is_paid=True
        )
        Transport.objects.create(order=order, courier="DSV")
        return order

    def test_stats_reflect_total_orders(self):
        self._make_complete_order("26KL 07-01/1")
        self._make_complete_order("26KL 07-02/1")
        response = self.client.get(reverse("main_offer_page"))
        # Completed orders are hidden by default, but still counted.
        self.assertEqual(response.context["completed_orders_count"], 2)

    def test_completed_orders_hidden_by_default(self):
        order = self._make_complete_order()
        response = self.client.get(reverse("main_offer_page"))
        self.assertNotIn(
            order, [card["order"] for card in response.context["order_cards"]]
        )

    def test_show_completed_query_param_reveals_them(self):
        order = self._make_complete_order()
        response = self.client.get(reverse("main_offer_page"), {"show_completed": "1"})
        self.assertIn(
            order, [card["order"] for card in response.context["order_cards"]]
        )

    def test_incomplete_order_always_shown(self):
        order = Order.objects.create(
            client=self.client_obj, contract_number="26KL 07-03/1"
        )
        response = self.client.get(reverse("main_offer_page"))
        self.assertIn(
            order, [card["order"] for card in response.context["order_cards"]]
        )


class MarkReminderSentViewTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="mz", password="pass123456789")
        self.client.login(username="mz", password="pass123456789")
        self.client_obj = Client.objects.create(client_name="Acme Furniture")
        self.order = Order.objects.create(
            client=self.client_obj, contract_number="26KL 07-01/1"
        )
        self.factory_order = FactoryOrder.objects.create(order=self.order)

    def test_marking_furniture_reminder_sent(self):
        url = reverse("mark_reminder_sent", args=["furniture", self.factory_order.id])
        response = self.client.post(url)
        self.factory_order.refresh_from_db()
        self.assertTrue(self.factory_order.is_furniture_reminder_sent)
        self.assertRedirects(response, reverse("main_offer_page"))

    def test_marking_package_reminder_sent(self):
        url = reverse("mark_reminder_sent", args=["package", self.factory_order.id])
        response = self.client.post(url)
        self.factory_order.refresh_from_db()
        self.assertTrue(self.factory_order.is_package_clarification_reminder_sent)

    def test_unknown_kind_returns_400_on_fetch_request(self):
        url = reverse("mark_reminder_sent", args=["bogus", self.factory_order.id])
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_get_request_not_allowed(self):
        url = reverse("mark_reminder_sent", args=["furniture", self.factory_order.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_nonexistent_factory_order_returns_404(self):
        url = reverse("mark_reminder_sent", args=["furniture", 999999])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_redirected_to_login(self):
        self.client.logout()
        url = reverse("mark_reminder_sent", args=["furniture", self.factory_order.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login_page"), response.url)


class MarkTransportReminderSentViewTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="mz", password="pass123456789")
        self.client.login(username="mz", password="pass123456789")
        client_obj = Client.objects.create(client_name="Acme Furniture")
        self.order = Order.objects.create(
            client=client_obj, contract_number="26KL 07-01/1"
        )
        self.transport = Transport.objects.create(order=self.order)

    def test_marking_transport_reminder_sent(self):
        url = reverse("mark_transport_reminder_sent", args=[self.order.id])
        self.client.post(url)
        self.transport.refresh_from_db()
        self.assertTrue(self.transport.is_reminder_sent)

    def test_fetch_request_returns_json_ok(self):
        url = reverse("mark_transport_reminder_sent", args=[self.order.id])
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(response.json(), {"ok": True})


class ToggleLanguageViewTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="mz", password="pass123456789")
        self.client.login(username="mz", password="pass123456789")

    def test_toggles_from_english_to_lithuanian(self):
        SiteSettings.objects.update_or_create(pk=1, defaults={"language": "en"})
        self.client.post(reverse("toggle_language"), HTTP_REFERER="/main_offer_page/")
        self.assertEqual(SiteSettings.get_language(), "lt")

    def test_toggles_back_from_lithuanian_to_english(self):
        SiteSettings.objects.update_or_create(pk=1, defaults={"language": "lt"})
        self.client.post(reverse("toggle_language"), HTTP_REFERER="/main_offer_page/")
        self.assertEqual(SiteSettings.get_language(), "en")

    def test_redirects_to_referer(self):
        response = self.client.post(
            reverse("toggle_language"), HTTP_REFERER="/main_offer_page/"
        )
        self.assertRedirects(response, "/main_offer_page/")

    def test_falls_back_to_main_offer_page_with_no_referer(self):
        response = self.client.post(reverse("toggle_language"))
        self.assertRedirects(response, reverse("main_offer_page"))

    def test_get_request_not_allowed(self):
        response = self.client.get(reverse("toggle_language"))
        self.assertEqual(response.status_code, 405)


class RecoverPasswordRequestViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="pass123456789")
        UserProfile.objects.create(user=self.user, phone_number="+37060012345")

    @patch("main.views.generate_and_send_recovery_code")
    def test_valid_username_creates_session_and_redirects(self, mock_send):
        response = self.client.post(
            reverse("recover_password_request_page"), {"username": "mz"}
        )
        self.assertRedirects(response, reverse("recover_password_verify_page"))
        self.assertTrue(mock_send.called)
        self.assertTrue(RecoverySession.objects.filter(user=self.user).exists())

    def test_nonexistent_username_still_redirects(self):
        # Deliberately doesn't reveal whether the username exists —
        # redirects to the same verify page regardless.
        response = self.client.post(
            reverse("recover_password_request_page"), {"username": "ghost"}
        )
        self.assertRedirects(response, reverse("recover_password_verify_page"))

    @patch("main.views.generate_and_send_recovery_code")
    def test_no_phone_on_file_shows_error(self, mock_send):
        from main.services import NoPhoneNumberOnFile

        mock_send.side_effect = NoPhoneNumberOnFile()
        response = self.client.post(
            reverse("recover_password_request_page"), {"username": "mz"}
        )
        self.assertContains(response, "No phone number on file")

    @patch("main.views.generate_and_send_recovery_code")
    def test_lockout_shows_error_with_time(self, mock_send):
        from main.services import RecoveryCodeLocked

        mock_send.side_effect = RecoveryCodeLocked(timezone.now() + timedelta(hours=1))
        response = self.client.post(
            reverse("recover_password_request_page"), {"username": "mz"}
        )
        self.assertContains(response, "Too many attempts")


class RecoverPasswordVerifyViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="pass123456789")
        self.session_obj = RecoverySession.objects.create(user=self.user)
        session = self.client.session
        session["recovery_username"] = "mz"
        session["recovery_session_id"] = self.session_obj.id
        session.save()

    def test_no_recovery_username_in_session_redirects_to_request_page(self):
        self.client.session.flush()
        response = self.client.get(reverse("recover_password_verify_page"))
        self.assertRedirects(response, reverse("recover_password_request_page"))

    @patch("main.views.verify_recovery_code")
    def test_correct_code_redirects_to_set_new_password(self, mock_verify):
        mock_verify.return_value = True
        response = self.client.post(
            reverse("recover_password_verify_page"), {"code": "12345678"}
        )
        self.assertRedirects(response, reverse("set_new_password_page"))
        self.assertIn("password_reset_token", self.client.session)

    @patch("main.views.verify_recovery_code")
    def test_incorrect_code_shows_error(self, mock_verify):
        mock_verify.return_value = False
        response = self.client.post(
            reverse("recover_password_verify_page"), {"code": "00000000"}
        )
        self.assertContains(response, "Invalid or expired code")


class SetNewPasswordViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="old-password-123")
        self.session_obj = RecoverySession.objects.create(user=self.user)
        self.token = signing.dumps({"user_id": self.user.id}, salt=RESET_TOKEN_SALT)
        session = self.client.session
        session["password_reset_token"] = self.token
        session["recovery_session_id"] = self.session_obj.id
        session.save()

    def test_no_token_in_session_redirects_to_login(self):
        self.client.session.flush()
        response = self.client.get(reverse("set_new_password_page"))
        self.assertRedirects(response, reverse("login_page"))

    def test_matching_passwords_reset_and_redirect(self):
        response = self.client.post(
            reverse("set_new_password_page"),
            {
                "password1": "brand-new-password-1",
                "password2": "brand-new-password-1",
            },
        )
        self.assertRedirects(response, reverse("login_page"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-password-1"))

    def test_mismatched_passwords_show_error(self):
        response = self.client.post(
            reverse("set_new_password_page"),
            {
                "password1": "brand-new-password-1",
                "password2": "different-password-2",
            },
        )
        self.assertContains(response, "don&#x27;t match")

    def test_too_short_password_shows_error(self):
        response = self.client.post(
            reverse("set_new_password_page"),
            {
                "password1": "short1",
                "password2": "short1",
            },
        )
        self.assertContains(response, "at least 14 characters")

    def test_successful_reset_marks_session_success(self):
        self.client.post(
            reverse("set_new_password_page"),
            {
                "password1": "brand-new-password-1",
                "password2": "brand-new-password-1",
            },
        )
        self.session_obj.refresh_from_db()
        self.assertEqual(self.session_obj.result, "success")


class LatestSyncTimeViewTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="mz", password="pass123456789")
        self.client.login(username="mz", password="pass123456789")

    def test_returns_null_when_no_sync_has_run(self):
        response = self.client.get(reverse("latest_sync_time"))
        self.assertEqual(response.json(), {"last_sync": None})

    def test_anonymous_user_redirected(self):
        self.client.logout()
        response = self.client.get(reverse("latest_sync_time"))
        self.assertEqual(response.status_code, 302)
