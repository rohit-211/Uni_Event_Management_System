from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Role, get_or_create_profile
from events.models import Event
from registrations.models import Registration, RegistrationStatus

from .forms import AttendanceMarkForm
from .models import Attendance, AttendanceStatus


def _role_for(user):
    if user.is_superuser:
        return Role.ADMIN
    return get_or_create_profile(user).role


def _managed_events(user, role):
    events = Event.objects.select_related('organiser')
    if role == Role.ORGANISER:
        return events.filter(organiser=user)
    if role == Role.ADMIN:
        return events
    raise PermissionDenied("Only organisers and administrators can manage attendance.")


@login_required
def attendance_dashboard_view(request):
    role = _role_for(request.user)
    if role == Role.STUDENT:
        return redirect('attendance:history')
    events = _managed_events(request.user, role).annotate(
        registration_count=Count(
            'registrations',
            filter=Q(registrations__status=RegistrationStatus.REGISTERED),
        ),
        present_count=Count(
            'registrations__attendance',
            filter=Q(
                registrations__status=RegistrationStatus.REGISTERED,
                registrations__attendance__status=AttendanceStatus.PRESENT,
            ),
        ),
    )
    return render(request, 'attendance/dashboard.html', {
        'events': events,
        'is_admin': role == Role.ADMIN,
    })


@login_required
def student_attendance_history_view(request):
    if _role_for(request.user) != Role.STUDENT:
        raise PermissionDenied("This attendance history is only available to the registered student.")

    registrations = Registration.objects.filter(
        user=request.user,
    ).select_related(
        'event', 'attendance', 'attendance__marked_by',
    ).order_by('-event__start_time', '-created_at')
    return render(request, 'attendance/student_history.html', {
        'registrations': registrations,
    })


@login_required
def event_attendees_view(request, event_id):
    role = _role_for(request.user)
    event = get_object_or_404(_managed_events(request.user, role), pk=event_id)

    if request.method == 'POST':
        form = AttendanceMarkForm(request.POST)
        if not form.is_valid():
            form.add_error(None, 'Submit a valid registered student and attendance status.')
            return _render_attendees(request, event, form=form, status=400)

        with transaction.atomic():
            registration = get_object_or_404(
                Registration.objects.select_for_update(),
                pk=form.cleaned_data['registration_id'],
                event=event,
                status=RegistrationStatus.REGISTERED,
            )
            attendance = Attendance.objects.select_for_update().filter(
                registration=registration,
            ).first()
            if attendance is None:
                attendance = Attendance(registration=registration)

            attendance.status = form.cleaned_data['status']
            attendance.marked_by = request.user
            attendance.checked_in_at = (
                timezone.now()
                if attendance.status == AttendanceStatus.PRESENT
                else None
            )
            attendance.full_clean()
            attendance.save()

        messages.success(
            request,
            f"Attendance updated for {registration.user.get_full_name() or registration.user.username}.",
        )
        return redirect('attendance:event_attendees', event_id=event.pk)

    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET', 'POST'])
    return _render_attendees(request, event)


def _render_attendees(request, event, form=None, status=200):
    registrations = Registration.objects.filter(
        event=event,
        status=RegistrationStatus.REGISTERED,
    ).select_related(
        'user', 'attendance',
    ).order_by('user__last_name', 'user__first_name', 'user__username')

    query = request.GET.get('q', '').strip()
    if query:
        registrations = registrations.filter(
            Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
        )

    selected_status = request.GET.get('status', '').strip()
    if selected_status == AttendanceStatus.PRESENT:
        registrations = registrations.filter(attendance__status=AttendanceStatus.PRESENT)
    elif selected_status == AttendanceStatus.ABSENT:
        registrations = registrations.filter(attendance__status=AttendanceStatus.ABSENT)
    elif selected_status == 'UNRECORDED':
        registrations = registrations.filter(attendance__isnull=True)

    attendee_rows = []
    for registration in registrations:
        attendance = getattr(registration, 'attendance', None)
        row_form = form if (
            form is not None
            and form.is_bound
            and str(form.data.get('registration_id', '')) == str(registration.pk)
        ) else AttendanceMarkForm(initial={
            'registration_id': registration.pk,
            'status': (
                attendance.status
                if attendance
                else AttendanceStatus.PRESENT
            ),
        })
        attendee_rows.append({'registration': registration, 'form': row_form})

    return render(request, 'attendance/event_attendees.html', {
        'event': event,
        'attendee_rows': attendee_rows,
        'search_query': query,
        'selected_status': selected_status,
        'status_choices': AttendanceStatus.choices,
    }, status=status)


@login_required
def event_attendance_report_view(request, event_id):
    role = _role_for(request.user)
    event = get_object_or_404(_managed_events(request.user, role), pk=event_id)
    registrations = Registration.objects.filter(
        event=event,
        status=RegistrationStatus.REGISTERED,
    )
    summary = registrations.aggregate(
        registered_count=Count('pk'),
        recorded_count=Count('attendance__pk'),
        present_count=Count(
            'attendance__pk',
            filter=Q(attendance__status=AttendanceStatus.PRESENT),
        ),
        absent_count=Count(
            'attendance__pk',
            filter=Q(attendance__status=AttendanceStatus.ABSENT),
        ),
    )
    summary['unrecorded_count'] = summary['registered_count'] - summary['recorded_count']
    summary['attendance_percentage'] = (
        round(summary['present_count'] * 100 / summary['recorded_count'], 1)
        if summary['recorded_count']
        else 0
    )
    summary['recording_coverage_percentage'] = (
        round(summary['recorded_count'] * 100 / summary['registered_count'], 1)
        if summary['registered_count']
        else 0
    )
    return render(request, 'attendance/event_report.html', {
        'event': event,
        'summary': summary,
    })
