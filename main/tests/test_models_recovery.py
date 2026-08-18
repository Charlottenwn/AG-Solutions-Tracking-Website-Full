"""
main/tests_models_recovery.py

Sanity tests for the password-recovery and notification-tracking models:
UserProfile, RecoveryCode, RecoveryLockout, RecoverySession,
RecoveryAttempt, NtfySentReminder.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from main.models import (
    UserProfile,
    RecoveryCode,
    RecoveryLockout,
    RecoverySession,
    RecoveryAttempt,
    NtfySentReminder,
    Status_recovery,
    Status_recovery_session,
)


class UserProfileModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="testpass123")

    def test_str_includes_username(self):
        profile = UserProfile.objects.create(
            user=self.user, phone_number="+37060012345"
        )
        self.assertEqual(str(profile), "Profile for mz")

    def test_phone_number_blank_by_default(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(profile.phone_number, "")

    def test_one_profile_per_user(self):
        UserProfile.objects.create(user=self.user, phone_number="+37060012345")
        with self.assertRaises(Exception):
            UserProfile.objects.create(user=self.user, phone_number="+37060099999")

    def test_profile_accessible_via_related_name(self):
        UserProfile.objects.create(user=self.user, phone_number="+37060012345")
        self.assertEqual(self.user.profile.phone_number, "+37060012345")


class RecoveryCodeModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="testpass123")

    def test_is_valid_true_for_fresh_unused_code(self):
        code = RecoveryCode.objects.create(
            user=self.user,
            code_hash="abc123",
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        self.assertTrue(code.is_valid())

    def test_is_valid_false_when_expired(self):
        code = RecoveryCode.objects.create(
            user=self.user,
            code_hash="abc123",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(code.is_valid())

    def test_is_valid_false_when_used(self):
        code = RecoveryCode.objects.create(
            user=self.user,
            code_hash="abc123",
            expires_at=timezone.now() + timedelta(minutes=10),
            used_at=timezone.now(),
        )
        self.assertFalse(code.is_valid())

    def test_is_valid_false_when_invalidated(self):
        code = RecoveryCode.objects.create(
            user=self.user,
            code_hash="abc123",
            expires_at=timezone.now() + timedelta(minutes=10),
            invalidated_at=timezone.now(),
        )
        self.assertFalse(code.is_valid())

    def test_multiple_codes_per_user_allowed(self):
        # No unique constraint on user — old codes get invalidated by
        # services.py logic, not by a DB constraint, so the model itself
        # should permit multiple rows.
        RecoveryCode.objects.create(
            user=self.user,
            code_hash="first",
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        RecoveryCode.objects.create(
            user=self.user,
            code_hash="second",
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        self.assertEqual(RecoveryCode.objects.filter(user=self.user).count(), 2)


class RecoveryLockoutModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="testpass123")

    def test_defaults(self):
        lockout = RecoveryLockout.objects.create(user=self.user)
        self.assertEqual(lockout.attempt_count, 0)
        self.assertIsNone(lockout.window_started_at)
        self.assertIsNone(lockout.locked_until)

    def test_one_lockout_row_per_user(self):
        RecoveryLockout.objects.create(user=self.user)
        with self.assertRaises(Exception):
            RecoveryLockout.objects.create(user=self.user)

    def test_accessible_via_related_name(self):
        RecoveryLockout.objects.create(user=self.user, attempt_count=3)
        self.assertEqual(self.user.recovery_lockout.attempt_count, 3)


class RecoverySessionModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="testpass123")

    def test_default_result_is_active(self):
        session = RecoverySession.objects.create(user=self.user)
        self.assertEqual(session.result, Status_recovery_session.ACTIVE)

    def test_started_at_auto_set(self):
        session = RecoverySession.objects.create(user=self.user)
        self.assertIsNotNone(session.started_at)

    def test_finished_at_null_until_explicitly_set(self):
        session = RecoverySession.objects.create(user=self.user)
        self.assertIsNone(session.finished_at)

    def test_str_includes_username_and_result(self):
        session = RecoverySession.objects.create(user=self.user)
        self.assertIn("mz", str(session))
        self.assertIn("active", str(session))


class RecoveryAttemptModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mz", password="testpass123")
        self.session = RecoverySession.objects.create(user=self.user)

    def test_default_status_is_initiated(self):
        attempt = RecoveryAttempt.objects.create(user=self.user, session=self.session)
        self.assertEqual(attempt.status, Status_recovery.INITIATED)

    def test_ordering_is_most_recent_first(self):
        first = RecoveryAttempt.objects.create(user=self.user, session=self.session)
        second = RecoveryAttempt.objects.create(user=self.user, session=self.session)
        attempts = list(RecoveryAttempt.objects.all())
        self.assertEqual(attempts[0].pk, second.pk)
        self.assertEqual(attempts[1].pk, first.pk)

    def test_session_can_be_null(self):
        # session is null=True — an attempt can theoretically exist without
        # a session (though in practice services.py always provides one).
        attempt = RecoveryAttempt.objects.create(user=self.user, session=None)
        self.assertIsNone(attempt.session)

    def test_session_deletion_cascades_to_attempts(self):
        RecoveryAttempt.objects.create(user=self.user, session=self.session)
        self.session.delete()
        self.assertEqual(RecoveryAttempt.objects.count(), 0)

    def test_detail_blank_by_default(self):
        attempt = RecoveryAttempt.objects.create(user=self.user, session=self.session)
        self.assertEqual(attempt.detail, "")

    def test_events_accessible_via_session_related_name(self):
        RecoveryAttempt.objects.create(
            user=self.user, session=self.session, status=Status_recovery.CODE_VERIFIED
        )
        self.assertEqual(self.session.events.count(), 1)
        self.assertEqual(
            self.session.events.first().status, Status_recovery.CODE_VERIFIED
        )


class NtfySentReminderModelTests(TestCase):
    def test_reminder_id_must_be_unique(self):
        NtfySentReminder.objects.create(reminder_id="transport-18")
        with self.assertRaises(Exception):
            NtfySentReminder.objects.create(reminder_id="transport-18")

    def test_last_sent_at_defaults_to_now(self):
        before = timezone.now()
        reminder = NtfySentReminder.objects.create(reminder_id="transport-18")
        after = timezone.now()
        self.assertTrue(before <= reminder.last_sent_at <= after)

    def test_str_includes_reminder_id(self):
        reminder = NtfySentReminder.objects.create(reminder_id="furniture-42")
        self.assertIn("furniture-42", str(reminder))

    def test_update_or_create_refreshes_last_sent_at(self):
        # Matches the actual usage pattern in tasks.py's check_reminders_task
        reminder, _ = NtfySentReminder.objects.update_or_create(
            reminder_id="package-7",
            defaults={"last_sent_at": timezone.now() - timedelta(days=1)},
        )
        old_time = reminder.last_sent_at
        reminder, created = NtfySentReminder.objects.update_or_create(
            reminder_id="package-7", defaults={"last_sent_at": timezone.now()}
        )
        self.assertFalse(created)
        self.assertGreater(reminder.last_sent_at, old_time)
