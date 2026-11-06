from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from attendance.models import Attendance, AttendanceStatus
from events.models import Event, EventStatus

from .models import Registration, RegistrationStatus

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RegistrationWorkflowTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='student_one',
            password='Password123!',
            email='student@uni.edu',
            first_name='Student',
            last_name='One',
        )
        self.other_student = User.objects.create_user(
            username='student_two',
            password='Password123!',
            email='second@uni.edu',
            first_name='Student',
            last_name='Two',
        )
        self.organiser = User.objects.create_user(
            username='organiser_one',
            password='Password123!',
            email='organiser@uni.edu',
        )
        self.organiser.profile.role = Role.ORGANISER
        self.organiser.profile.save()
        self.other_organiser = User.objects.create_user(
            username='organiser_two',
            password='Password123!',
        )
        self.other_organiser.profile.role = Role.ORGANISER
        self.other_organiser.profile.save()
        self.admin = User.objects.create_superuser(
            username='admin_one',
            password='Password123!',
            email='admin@uni.edu',
        )
        now = timezone.now()
        self.event = Event.objects.create(
            title='Published workshop',
            venue='Engineering Hall',
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=2),
            registration_deadline=now + timedelta(days=1),
            max_participants=2,
            organiser=self.organiser,
            status=EventStatus.PUBLISHED,
        )
        self.other_event = Event.objects.create(
            title='Other organiser workshop',
            start_time=now + timedelta(days=3),
            end_time=now + timedelta(days=3, hours=2),
            organiser=self.other_organiser,
            status=EventStatus.PUBLISHED,
        )

    def register(self, student=None, event=None):
        student = student or self.student
        event = event or self.event
        self.client.force_login(student)
        return self.client.post(reverse('registrations:register', args=[event.pk]))

    def test_student_successfully_registers_and_sees_success_page(self):
        response = self.register()

        registration = Registration.objects.get(event=self.event, user=self.student)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('registrations:success', args=[registration.pk]))
        self.assertEqual(registration.status, RegistrationStatus.REGISTERED)
        self.assertEqual(self.event.registrations.count(), 1)

    def test_registration_requires_post(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('registrations:register', args=[self.event.pk]))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(Registration.objects.exists())

    def test_duplicate_registration_is_handled_and_unique_constraint_remains(self):
        self.register()
        response = self.register()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Registration.objects.filter(event=self.event, user=self.student).count(),
            1,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Registration.objects.create(event=self.event, user=self.student)

    def test_cancelled_registration_is_reactivated_without_duplicate_record(self):
        registration = Registration.objects.create(
            event=self.event,
            user=self.student,
            status=RegistrationStatus.CANCELLED,
        )

        self.register()

        registration.refresh_from_db()
        self.assertEqual(registration.status, RegistrationStatus.REGISTERED)
        self.assertEqual(Registration.objects.filter(event=self.event, user=self.student).count(), 1)

    def test_student_cannot_register_for_unpublished_or_unapproved_event(self):
        for status in (EventStatus.PENDING, EventStatus.APPROVED, EventStatus.REJECTED):
            event = Event.objects.create(
                title=f'{status} event',
                start_time=timezone.now() + timedelta(days=4),
                end_time=timezone.now() + timedelta(days=4, hours=1),
                organiser=self.organiser,
                status=status,
                rejection_reason='Not approved' if status == EventStatus.REJECTED else '',
            )
            response = self.register(event=event)

            self.assertEqual(response.status_code, 302)
            self.assertFalse(Registration.objects.filter(event=event).exists())

    def test_student_cannot_register_after_deadline_or_event_start(self):
        self.event.registration_deadline = timezone.now() - timedelta(seconds=1)
        self.event.save()
        response_after_deadline = self.register()
        self.assertFalse(Registration.objects.filter(event=self.event).exists())

        self.event.registration_deadline = None
        self.event.start_time = timezone.now() - timedelta(minutes=5)
        self.event.end_time = timezone.now() + timedelta(minutes=30)
        self.event.save()
        response_after_start = self.register()

        self.assertEqual(response_after_deadline.status_code, 302)
        self.assertEqual(response_after_start.status_code, 302)
        self.assertFalse(Registration.objects.filter(event=self.event).exists())

    def test_full_event_rejects_registration(self):
        Registration.objects.create(event=self.event, user=self.other_student)
        another_student = User.objects.create_user(username='student_full')
        Registration.objects.create(event=self.event, user=another_student)
        third_student = User.objects.create_user(username='student_three')
        response = self.register(student=third_student)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Registration.objects.filter(event=self.event, user=third_student).exists())

    def test_cancelled_registrations_do_not_occupy_capacity(self):
        first = Registration.objects.create(event=self.event, user=self.student)
        Registration.objects.create(event=self.event, user=self.other_student)
        self.client.force_login(self.student)
        self.client.post(reverse('registrations:cancel', args=[self.event.pk]))

        third_student = User.objects.create_user(username='student_three')
        self.register(student=third_student)

        first.refresh_from_db()
        self.assertEqual(first.status, RegistrationStatus.CANCELLED)
        self.assertTrue(
            Registration.objects.filter(
                event=self.event,
                user=third_student,
                status=RegistrationStatus.REGISTERED,
            ).exists()
        )

    def test_student_can_cancel_own_registration_before_event_starts(self):
        registration = Registration.objects.create(event=self.event, user=self.student)
        self.client.force_login(self.student)

        response = self.client.post(reverse('registrations:cancel', args=[self.event.pk]))

        registration.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(registration.status, RegistrationStatus.CANCELLED)
        self.assertTrue(Registration.objects.filter(pk=registration.pk).exists())

    def test_student_cannot_cancel_another_students_registration(self):
        registration = Registration.objects.create(event=self.event, user=self.other_student)
        self.client.force_login(self.student)

        response = self.client.post(reverse('registrations:cancel', args=[self.event.pk]))

        registration.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(registration.status, RegistrationStatus.REGISTERED)

    def test_student_cannot_cancel_after_event_has_started(self):
        registration = Registration.objects.create(event=self.event, user=self.student)
        self.event.start_time = timezone.now() - timedelta(minutes=1)
        self.event.save()
        self.client.force_login(self.student)

        response = self.client.post(reverse('registrations:cancel', args=[self.event.pk]))

        registration.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(registration.status, RegistrationStatus.REGISTERED)

    def test_student_only_sees_and_opens_own_registrations(self):
        own_registration = Registration.objects.create(event=self.event, user=self.student)
        other_registration = Registration.objects.create(event=self.other_event, user=self.other_student)
        self.client.force_login(self.student)

        listing = self.client.get(reverse('registrations:my_registrations'))
        own_detail = self.client.get(reverse('registrations:detail', args=[own_registration.pk]))
        other_detail = self.client.get(reverse('registrations:detail', args=[other_registration.pk]))

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            {item.pk for item in listing.context['registrations']},
            {own_registration.pk},
        )
        self.assertEqual(own_detail.status_code, 200)
        self.assertEqual(other_detail.status_code, 403)

    def test_organiser_can_only_view_registrations_for_owned_event(self):
        own_registration = Registration.objects.create(event=self.event, user=self.student)
        other_registration = Registration.objects.create(event=self.other_event, user=self.other_student)
        self.client.force_login(self.organiser)

        own_roster = self.client.get(
            reverse('registrations:participants', args=[self.event.pk]),
        )
        other_roster = self.client.get(
            reverse('registrations:participants', args=[self.other_event.pk]),
        )
        own_detail = self.client.get(reverse('registrations:detail', args=[own_registration.pk]))
        other_detail = self.client.get(reverse('registrations:detail', args=[other_registration.pk]))

        self.assertEqual(own_roster.status_code, 200)
        self.assertEqual(other_roster.status_code, 403)
        self.assertEqual(own_detail.status_code, 200)
        self.assertEqual(other_detail.status_code, 403)

    def test_admin_can_view_all_registrations_and_details(self):
        registration = Registration.objects.create(event=self.other_event, user=self.other_student)
        self.client.force_login(self.admin)

        listing = self.client.get(reverse('registrations:manage'))
        detail = self.client.get(reverse('registrations:admin_detail', args=[registration.pk]))

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.context['registrations'].count(), 1)
        self.assertEqual(detail.status_code, 200)

    def test_admin_can_correct_registration_status_with_capacity_check(self):
        registration = Registration.objects.create(
            event=self.event,
            user=self.student,
            status=RegistrationStatus.CANCELLED,
        )
        Registration.objects.create(event=self.event, user=self.other_student)
        self.event.max_participants = 1
        self.event.save()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('registrations:admin_detail', args=[registration.pk]),
            {'status': RegistrationStatus.REGISTERED},
        )

        registration.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(registration.status, RegistrationStatus.CANCELLED)

    def test_organiser_roster_search_and_counters(self):
        Registration.objects.create(event=self.event, user=self.student)
        Registration.objects.create(
            event=self.event,
            user=self.other_student,
            status=RegistrationStatus.CANCELLED,
        )
        self.client.force_login(self.organiser)

        response = self.client.get(
            reverse('registrations:participants', args=[self.event.pk]),
            {'q': 'student@uni.edu', 'status': RegistrationStatus.REGISTERED},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['counts']['total'], 2)
        self.assertEqual(response.context['counts']['registered'], 1)
        self.assertEqual(response.context['counts']['cancelled'], 1)
        self.assertEqual(response.context['available_seats'], 1)
        self.assertEqual(len(response.context['registrations']), 1)

    def test_attendance_remains_linked_to_registration(self):
        registration = Registration.objects.create(event=self.event, user=self.student)
        attendance = Attendance.objects.create(
            registration=registration,
            status=AttendanceStatus.PRESENT,
        )
        self.client.force_login(self.organiser)

        response = self.client.get(
            reverse('registrations:participants', args=[self.event.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(attendance.registration, registration)
        self.assertContains(response, 'Present')

    def test_unauthenticated_student_registration_redirects_to_login(self):
        response = self.client.post(reverse('registrations:register', args=[self.event.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)
