from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from attendance.models import Attendance, AttendanceStatus
from events.models import Event
from registrations.models import Registration, RegistrationStatus

User = get_user_model()


class AttendanceAccessAndManagementTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='student_one',
            password='Password123!',
            email='student@uni.edu',
        )
        self.other_student = User.objects.create_user(
            username='student_two',
            password='Password123!',
            email='other@uni.edu',
        )
        self.organiser = User.objects.create_user(
            username='organiser_one',
            password='Password123!',
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
            title='Owned event',
            organiser=self.organiser,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=2),
            is_published=True,
        )
        self.other_event = Event.objects.create(
            title='Other event',
            organiser=self.other_organiser,
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=2),
            is_published=True,
        )
        self.registration = Registration.objects.create(
            event=self.event,
            user=self.student,
        )
        self.other_registration = Registration.objects.create(
            event=self.event,
            user=self.other_student,
        )
        self.other_event_registration = Registration.objects.create(
            event=self.other_event,
            user=self.student,
        )

    def test_student_sees_only_their_own_attendance_history(self):
        own_attendance = Attendance.objects.create(
            registration=self.registration,
            status=AttendanceStatus.PRESENT,
        )
        Attendance.objects.create(
            registration=self.other_registration,
            status=AttendanceStatus.ABSENT,
        )

        self.client.force_login(self.student)
        response = self.client.get(reverse('attendance:history'))

        self.assertEqual(response.status_code, 200)
        registrations = list(response.context['registrations'])
        self.assertEqual(
            {registration.pk for registration in registrations},
            {self.registration.pk, self.other_event_registration.pk},
        )
        self.assertIn(own_attendance, [r.attendance for r in registrations if hasattr(r, 'attendance')])

    def test_student_cannot_mark_attendance(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('attendance:event_attendees', args=[self.event.pk]),
            {'registration_id': self.registration.pk, 'status': AttendanceStatus.PRESENT},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Attendance.objects.exists())

    def test_organiser_can_access_only_owned_event_attendees(self):
        self.client.force_login(self.organiser)

        own_response = self.client.get(
            reverse('attendance:event_attendees', args=[self.event.pk]),
        )
        other_response = self.client.get(
            reverse('attendance:event_attendees', args=[self.other_event.pk]),
        )

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)

    def test_organiser_marks_and_corrects_attendance_for_own_event(self):
        self.client.force_login(self.organiser)
        url = reverse('attendance:event_attendees', args=[self.event.pk])

        present_response = self.client.post(url, {
            'registration_id': self.registration.pk,
            'status': AttendanceStatus.PRESENT,
        })
        attendance = Attendance.objects.get(registration=self.registration)
        original_checkin = attendance.checked_in_at

        absent_response = self.client.post(url, {
            'registration_id': self.registration.pk,
            'status': AttendanceStatus.ABSENT,
        })
        attendance.refresh_from_db()

        self.assertEqual(present_response.status_code, 302)
        self.assertEqual(absent_response.status_code, 302)
        self.assertEqual(attendance.status, AttendanceStatus.ABSENT)
        self.assertIsNone(attendance.checked_in_at)
        self.assertEqual(attendance.marked_by, self.organiser)
        self.assertIsNotNone(original_checkin)

    def test_organiser_cannot_modify_another_organisers_attendance(self):
        other_registration = self.other_event_registration
        existing = Attendance.objects.create(
            registration=other_registration,
            status=AttendanceStatus.PRESENT,
            marked_by=self.other_organiser,
        )
        self.client.force_login(self.organiser)
        response = self.client.post(
            reverse('attendance:event_attendees', args=[self.other_event.pk]),
            {
                'registration_id': other_registration.pk,
                'status': AttendanceStatus.ABSENT,
            },
        )

        self.assertEqual(response.status_code, 404)
        existing.refresh_from_db()
        self.assertEqual(existing.status, AttendanceStatus.PRESENT)
        self.assertEqual(existing.marked_by, self.other_organiser)

    def test_admin_can_manage_attendance_across_events(self):
        self.client.force_login(self.admin)
        dashboard = self.client.get(reverse('attendance:dashboard'))
        manage = self.client.post(
            reverse('attendance:event_attendees', args=[self.other_event.pk]),
            {
                'registration_id': self.other_event_registration.pk,
                'status': AttendanceStatus.PRESENT,
            },
        )

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(manage.status_code, 302)
        self.assertTrue(Attendance.objects.filter(registration=self.other_event_registration).exists())

    def test_only_active_registration_for_selected_event_can_be_marked(self):
        self.client.force_login(self.organiser)
        url = reverse('attendance:event_attendees', args=[self.event.pk])

        wrong_event_response = self.client.post(url, {
            'registration_id': self.other_event_registration.pk,
            'status': AttendanceStatus.PRESENT,
        })
        cancelled = Registration.objects.create(
            event=self.event,
            user=User.objects.create_user(username='cancelled_student'),
            status=RegistrationStatus.CANCELLED,
        )
        cancelled_response = self.client.post(url, {
            'registration_id': cancelled.pk,
            'status': AttendanceStatus.PRESENT,
        })

        self.assertEqual(wrong_event_response.status_code, 404)
        self.assertEqual(cancelled_response.status_code, 404)
        self.assertFalse(Attendance.objects.exists())

    def test_duplicate_attendance_is_prevented_by_database_constraint(self):
        Attendance.objects.create(registration=self.registration)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attendance.objects.create(registration=self.registration)

    def test_unauthenticated_attendance_access_redirects_to_login(self):
        response = self.client.get(reverse('attendance:dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_invalid_status_post_is_rejected_without_creating_attendance(self):
        self.client.force_login(self.organiser)
        response = self.client.post(
            reverse('attendance:event_attendees', args=[self.event.pk]),
            {'registration_id': self.registration.pk, 'status': 'NOT_A_STATUS'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Attendance.objects.exists())

    def test_unrecorded_students_are_not_counted_as_absent_in_report(self):
        Attendance.objects.create(
            registration=self.registration,
            status=AttendanceStatus.PRESENT,
        )
        Attendance.objects.create(
            registration=self.other_registration,
            status=AttendanceStatus.ABSENT,
        )
        self.client.force_login(self.organiser)
        response = self.client.get(
            reverse('attendance:event_report', args=[self.event.pk]),
        )

        summary = response.context['summary']
        self.assertEqual(summary['registered_count'], 2)
        self.assertEqual(summary['recorded_count'], 2)
        self.assertEqual(summary['present_count'], 1)
        self.assertEqual(summary['absent_count'], 1)
        self.assertEqual(summary['unrecorded_count'], 0)
        self.assertEqual(summary['attendance_percentage'], 50)
        self.assertEqual(summary['recording_coverage_percentage'], 100)

    def test_report_handles_zero_registrations(self):
        empty_event = Event.objects.create(
            title='Empty event',
            organiser=self.organiser,
            start_time=timezone.now() + timedelta(days=3),
            end_time=timezone.now() + timedelta(days=3, hours=1),
        )
        self.client.force_login(self.organiser)
        response = self.client.get(
            reverse('attendance:event_report', args=[empty_event.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['attendance_percentage'], 0)
        self.assertEqual(response.context['summary']['recording_coverage_percentage'], 0)
