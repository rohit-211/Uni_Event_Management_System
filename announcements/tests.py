from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.exceptions import ValidationError

from accounts.models import Role
from announcements.models import Announcement, Audience, Priority, Status
from announcements.forms import AnnouncementForm

User = get_user_model()


class AnnouncementModelAndFormTests(TestCase):
    """
    Tests for Announcement model fields, auto-publication dates, string representation, and form validation.
    """

    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='admin_announcer',
            password='Password123!',
            email='admin@uni.edu'
        )
        self.org_user = User.objects.create_user(
            username='org_announcer',
            password='Password123!',
            email='org@uni.edu'
        )
        self.org_user.profile.role = Role.ORGANISER
        self.org_user.profile.save()

    def test_announcement_publication_timestamp_auto_populates(self):
        """Published announcements must automatically receive a published_at timestamp."""
        announcement = Announcement.objects.create(
            title='Campus Tech Fest 2026',
            content='Full schedule details announced for the annual fest.',
            creator=self.admin_user,
            audience=Audience.ALL,
            priority=Priority.IMPORTANT,
            status=Status.PUBLISHED
        )
        self.assertIsNotNone(announcement.published_at)
        self.assertTrue(announcement.is_published)
        self.assertTrue(announcement.is_important)
        self.assertIn('Campus Tech Fest 2026', str(announcement))

    def test_announcement_draft_clears_publication_timestamp(self):
        """Drafts should not have an active published_at timestamp."""
        announcement = Announcement.objects.create(
            title='Draft Work in Progress',
            content='Internal notes regarding upcoming venue maintenance.',
            creator=self.admin_user,
            status=Status.DRAFT
        )
        self.assertIsNone(announcement.published_at)
        self.assertFalse(announcement.is_published)

    def test_form_validation_for_short_content(self):
        """Form must reject announcements with titles shorter than 5 chars or content under 10 chars."""
        form = AnnouncementForm(
            data={
                'title': 'Hi',
                'content': 'Short',
                'audience': Audience.ALL,
                'priority': Priority.NORMAL,
                'status': Status.PUBLISHED
            },
            user=self.admin_user
        )
        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)
        self.assertIn('content', form.errors)

    def test_form_restricts_organiser_from_choosing_all_audience(self):
        """Organisers cannot select 'ALL' audience; form rejects it with a validation error."""
        form = AnnouncementForm(
            data={
                'title': 'Valid Headline For Event',
                'content': 'Valid description with more than 10 characters.',
                'audience': Audience.ALL,  # Malicious/tampered selection by Organiser
                'priority': Priority.NORMAL,
                'status': Status.PUBLISHED
            },
            user=self.org_user
        )
        self.assertFalse(form.is_valid())
        self.assertIn('audience', form.errors)

    def test_event_title_association(self):
        """Event title should be successfully stored and linked to the announcement."""
        announcement = Announcement.objects.create(
            title='Hackathon Rulebook',
            content='Review the eligibility criteria for the 24h coding sprint.',
            creator=self.org_user,
            event_title='Annual Hackathon 2026',
            audience=Audience.STUDENTS,
            status=Status.PUBLISHED
        )
        self.assertEqual(announcement.event_title, 'Annual Hackathon 2026')


class AnnouncementAccessAndPermissionsTests(TestCase):
    """
    Tests for role-based viewing, creating, editing, and deleting permissions.
    """

    def setUp(self):
        self.client = Client()

        # 1. Admin
        self.admin = User.objects.create_superuser(username='admin_alice', password='Password123!')
        self.admin.profile.role = Role.ADMIN
        self.admin.profile.save()

        # 2. Organiser A
        self.org_a = User.objects.create_user(username='org_bob', password='Password123!')
        self.org_a.profile.role = Role.ORGANISER
        self.org_a.profile.save()

        # 3. Organiser B
        self.org_b = User.objects.create_user(username='org_charlie', password='Password123!')
        self.org_b.profile.role = Role.ORGANISER
        self.org_b.profile.save()

        # 4. Student
        self.student = User.objects.create_user(username='student_dave', password='Password123!')
        self.student.profile.role = Role.STUDENT
        self.student.profile.save()

        # Sample announcements
        self.pub_all = Announcement.objects.create(
            title='Campus Holiday Notice',
            content='University will remain closed on Friday for National Holiday.',
            creator=self.admin,
            audience=Audience.ALL,
            priority=Priority.NORMAL,
            status=Status.PUBLISHED
        )
        self.pub_students = Announcement.objects.create(
            title='End-Semester Exam Schedule',
            content='Detailed exam timetable is now uploaded for all engineering departments.',
            creator=self.admin,
            audience=Audience.STUDENTS,
            priority=Priority.URGENT,
            status=Status.PUBLISHED
        )
        self.pub_organisers = Announcement.objects.create(
            title='Auditorium Booking Guidelines',
            content='New reservation procedure for campus auditoriums and sound systems.',
            creator=self.admin,
            audience=Audience.ORGANISERS,
            priority=Priority.IMPORTANT,
            status=Status.PUBLISHED
        )
        self.draft_admin = Announcement.objects.create(
            title='Draft Budget Meeting',
            content='Confidential meeting agenda for campus administrators.',
            creator=self.admin,
            audience=Audience.ALL,
            status=Status.DRAFT
        )
        self.draft_org_a = Announcement.objects.create(
            title='Organiser Bob Draft Notice',
            content='Draft announcement for Robotics Club workshop.',
            creator=self.org_a,
            audience=Audience.STUDENTS,
            status=Status.DRAFT
        )

    def test_unauthenticated_user_feed_sees_only_published_all(self):
        """Unauthenticated public visitors can only see published ALL notices."""
        response = self.client.get(reverse('announcements:list'))
        self.assertEqual(response.status_code, 200)
        announcements = response.context['announcements']
        self.assertIn(self.pub_all, announcements)
        self.assertNotIn(self.pub_students, announcements)
        self.assertNotIn(self.pub_organisers, announcements)
        self.assertNotIn(self.draft_admin, announcements)

    def test_student_feed_sees_all_and_student_notices(self):
        """Students see published ALL and STUDENTS notices, never DRAFTS or ORGANISER-only notices."""
        self.client.login(username='student_dave', password='Password123!')
        response = self.client.get(reverse('announcements:list'))
        announcements = response.context['announcements']
        self.assertIn(self.pub_all, announcements)
        self.assertIn(self.pub_students, announcements)
        self.assertNotIn(self.pub_organisers, announcements)
        self.assertNotIn(self.draft_admin, announcements)
        self.assertNotIn(self.draft_org_a, announcements)

    def test_organiser_feed_sees_all_organisers_and_own_drafts(self):
        """Organiser Bob sees ALL, ORGANISERS notices, and his own draft, but not Admin's draft or Student-only."""
        self.client.login(username='org_bob', password='Password123!')
        response = self.client.get(reverse('announcements:list'))
        announcements = response.context['announcements']
        self.assertIn(self.pub_all, announcements)
        self.assertIn(self.pub_organisers, announcements)
        self.assertIn(self.draft_org_a, announcements)
        self.assertNotIn(self.draft_admin, announcements)

    def test_admin_feed_sees_all_announcements_and_drafts(self):
        """Admins see every announcement across all audiences and lifecycle statuses."""
        self.client.login(username='admin_alice', password='Password123!')
        response = self.client.get(reverse('announcements:list'))
        announcements = response.context['announcements']
        self.assertIn(self.pub_all, announcements)
        self.assertIn(self.pub_students, announcements)
        self.assertIn(self.pub_organisers, announcements)
        self.assertIn(self.draft_admin, announcements)
        self.assertIn(self.draft_org_a, announcements)

    def test_student_cannot_view_organiser_only_announcement_detail(self):
        """Students accessing an organiser-only announcement detail page receive HTTP 403 Forbidden."""
        self.client.login(username='student_dave', password='Password123!')
        response = self.client.get(reverse('announcements:detail', kwargs={'pk': self.pub_organisers.pk}))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_view_draft_detail(self):
        """Students accessing any draft announcement receive HTTP 403 Forbidden."""
        self.client.login(username='student_dave', password='Password123!')
        response = self.client.get(reverse('announcements:detail', kwargs={'pk': self.draft_admin.pk}))
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_create_announcement(self):
        """Students attempting to access create view receive HTTP 403 Forbidden."""
        self.client.login(username='student_dave', password='Password123!')
        response = self.client.get(reverse('announcements:create'))
        self.assertEqual(response.status_code, 403)

        post_response = self.client.post(reverse('announcements:create'), {
            'title': 'Student Hack Announcement',
            'content': 'This should not be allowed at all.',
            'audience': Audience.ALL,
            'priority': Priority.URGENT,
            'status': Status.PUBLISHED
        })
        self.assertEqual(post_response.status_code, 403)

    def test_organiser_can_create_student_announcement(self):
        """Organisers can successfully post announcements targeted to Students."""
        self.client.login(username='org_bob', password='Password123!')
        payload = {
            'title': 'Robotics Workshop Registration Open',
            'content': 'Hands-on Arduino and Raspberry Pi session this Saturday.',
            'audience': Audience.STUDENTS,
            'priority': Priority.NORMAL,
            'status': Status.PUBLISHED,
            'event_title': 'Robotics Expo 2026'
        }
        response = self.client.post(reverse('announcements:create'), data=payload)
        self.assertEqual(response.status_code, 302)

        created = Announcement.objects.get(title='Robotics Workshop Registration Open')
        self.assertEqual(created.creator, self.org_a)
        self.assertEqual(created.event_title, 'Robotics Expo 2026')
        self.assertEqual(created.audience, Audience.STUDENTS)

    def test_organiser_cannot_edit_another_organisers_announcement(self):
        """Organiser Bob cannot edit an announcement created by Organiser Charlie."""
        charlie_notice = Announcement.objects.create(
            title='Music Club Auditions',
            content='Sign ups for campus vocal and instrumental bands.',
            creator=self.org_b,
            audience=Audience.STUDENTS,
            status=Status.PUBLISHED
        )
        self.client.login(username='org_bob', password='Password123!')
        response = self.client.get(reverse('announcements:edit', kwargs={'pk': charlie_notice.pk}))
        self.assertEqual(response.status_code, 403)

        post_response = self.client.post(reverse('announcements:edit', kwargs={'pk': charlie_notice.pk}), {
            'title': 'Hacked Title',
            'content': 'Content overwritten illegally by non-author.',
            'audience': Audience.STUDENTS,
            'priority': Priority.NORMAL,
            'status': Status.PUBLISHED
        })
        self.assertEqual(post_response.status_code, 403)
        charlie_notice.refresh_from_db()
        self.assertEqual(charlie_notice.title, 'Music Club Auditions')

    def test_organiser_cannot_delete_another_organisers_announcement(self):
        """Organiser Bob cannot delete Organiser Charlie's announcement."""
        charlie_notice = Announcement.objects.create(
            title='Dance Auditions',
            content='Dance tryouts at open air theatre.',
            creator=self.org_b,
            audience=Audience.STUDENTS,
            status=Status.PUBLISHED
        )
        self.client.login(username='org_bob', password='Password123!')
        response = self.client.post(reverse('announcements:delete', kwargs={'pk': charlie_notice.pk}))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Announcement.objects.filter(pk=charlie_notice.pk).exists())

    def test_admin_can_edit_and_delete_any_announcement(self):
        """Administrators have full management access over any announcement."""
        charlie_notice = Announcement.objects.create(
            title='Drama Club Tryouts',
            content='Drama club tryouts scheduled for next week.',
            creator=self.org_b,
            audience=Audience.STUDENTS,
            status=Status.PUBLISHED
        )
        self.client.login(username='admin_alice', password='Password123!')

        # 1. Edit
        edit_response = self.client.post(reverse('announcements:edit', kwargs={'pk': charlie_notice.pk}), {
            'title': 'Drama Club Tryouts - Updated by Admin',
            'content': 'Venue has been moved to Seminar Hall 2.',
            'audience': Audience.STUDENTS,
            'priority': Priority.IMPORTANT,
            'status': Status.PUBLISHED
        })
        self.assertEqual(edit_response.status_code, 302)
        charlie_notice.refresh_from_db()
        self.assertEqual(charlie_notice.title, 'Drama Club Tryouts - Updated by Admin')

        # 2. Delete
        delete_response = self.client.post(reverse('announcements:delete', kwargs={'pk': charlie_notice.pk}))
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(Announcement.objects.filter(pk=charlie_notice.pk).exists())

    def test_toggle_publish_action(self):
        """Authorized author or admin can toggle draft/published status."""
        self.client.login(username='org_bob', password='Password123!')
        self.assertEqual(self.draft_org_a.status, Status.DRAFT)

        # Toggle to PUBLISHED
        response = self.client.post(reverse('announcements:toggle_publish', kwargs={'pk': self.draft_org_a.pk}))
        self.assertEqual(response.status_code, 302)
        self.draft_org_a.refresh_from_db()
        self.assertEqual(self.draft_org_a.status, Status.PUBLISHED)
        self.assertIsNotNone(self.draft_org_a.published_at)

        # Toggle back to DRAFT
        response2 = self.client.post(reverse('announcements:toggle_publish', kwargs={'pk': self.draft_org_a.pk}))
        self.assertEqual(response2.status_code, 302)
        self.draft_org_a.refresh_from_db()
        self.assertEqual(self.draft_org_a.status, Status.DRAFT)
        self.assertIsNone(self.draft_org_a.published_at)

    def test_unauthenticated_access_to_create_redirects_to_login(self):
        """Unauthenticated requests to create view redirect to login."""
        response = self.client.get(reverse('announcements:create'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('accounts:login')))
