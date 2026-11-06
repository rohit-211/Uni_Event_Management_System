import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import admin_required, student_required
from accounts.models import Role, get_or_create_profile
from attendance.models import AttendanceStatus
from events.models import Event, EventStatus

from .forms import RegistrationAdminStatusForm
from .models import Registration, RegistrationStatus


def _get_user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return Role.ADMIN
    return get_or_create_profile(user).role


def _event_registration_queryset(event):
    return Registration.objects.filter(event=event).select_related(
        'user',
        'user__profile',
        'attendance',
    )


def _registration_list_filters(queryset, request):
    search_query = request.GET.get('q', '').strip()
    if search_query:
        queryset = queryset.filter(
            Q(user__username__icontains=search_query)
            | Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
            | Q(user__email__icontains=search_query)
        )

    selected_status = request.GET.get('status', '').strip()
    if selected_status in RegistrationStatus.values:
        queryset = queryset.filter(status=selected_status)
    else:
        selected_status = ''
    return queryset, search_query, selected_status


def _registration_counts(queryset):
    return queryset.aggregate(
        total=Count('pk'),
        registered=Count('pk', filter=Q(status=RegistrationStatus.REGISTERED)),
        cancelled=Count('pk', filter=Q(status=RegistrationStatus.CANCELLED)),
    )


def _redirect_to_event(request, event, message, level=messages.error):
    level(request, message)
    if event.status == EventStatus.PUBLISHED:
        return redirect('events:detail', pk=event.pk)
    return redirect('events:list')


@student_required
def register_for_event_view(request, event_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if _get_user_role(request.user) != Role.STUDENT:
        raise PermissionDenied("Only students can register for events.")

    try:
        with transaction.atomic():
            event = get_object_or_404(
                Event.objects.select_for_update(),
                pk=event_id,
            )
            now = timezone.now()
            if event.status != EventStatus.PUBLISHED:
                failure = "Registrations are only open for published events."
            elif event.start_time <= now:
                failure = "Registration is closed because this event has started."
            elif event.registration_deadline and event.registration_deadline <= now:
                failure = "The registration deadline for this event has passed."
            else:
                failure = None

            if failure:
                return _redirect_to_event(request, event, failure)

            registration = Registration.objects.select_for_update().filter(
                event=event,
                user=request.user,
            ).first()
            if registration and registration.status == RegistrationStatus.REGISTERED:
                messages.info(request, "You are already registered for this event.")
                return redirect('registrations:detail', pk=registration.pk)

            active_count = Registration.objects.filter(
                event=event,
                status=RegistrationStatus.REGISTERED,
            ).count()
            if (
                event.max_participants is not None
                and active_count >= event.max_participants
            ):
                return _redirect_to_event(
                    request,
                    event,
                    "Registration is full; the participant limit has been reached.",
                )

            if registration:
                registration.status = RegistrationStatus.REGISTERED
                registration.save(update_fields=['status', 'updated_at'])
                created = False
            else:
                registration = Registration.objects.create(
                    event=event,
                    user=request.user,
                    status=RegistrationStatus.REGISTERED,
                )
                created = True
    except IntegrityError:
        if not Registration.objects.filter(
            event_id=event_id,
            user=request.user,
            status=RegistrationStatus.REGISTERED,
        ).exists():
            raise
        messages.info(request, "You are already registered for this event.")
        return redirect('events:detail', pk=event_id)

    if created:
        messages.success(request, f"You are registered for '{event.title}'.")
        return redirect('registrations:success', pk=registration.pk)

    messages.success(request, f"Your registration for '{event.title}' has been reactivated.")
    return redirect('registrations:detail', pk=registration.pk)


@student_required
def cancel_registration_view(request, event_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if _get_user_role(request.user) != Role.STUDENT:
        raise PermissionDenied("Only students can cancel their own registrations.")

    with transaction.atomic():
        event = get_object_or_404(Event.objects.select_for_update(), pk=event_id)
        registration = get_object_or_404(
            Registration.objects.select_for_update(),
            event=event,
            user=request.user,
        )
        if registration.status == RegistrationStatus.CANCELLED:
            messages.info(request, "Your registration was already cancelled.")
        elif timezone.now() >= event.start_time:
            messages.error(
                request,
                "Registration cancellation is only permitted before the event starts.",
            )
        else:
            registration.status = RegistrationStatus.CANCELLED
            registration.save(update_fields=['status', 'updated_at'])
            messages.success(request, f"Your registration for '{event.title}' was cancelled.")

    return redirect('registrations:detail', pk=registration.pk)


@student_required
def my_registrations_view(request):
    if _get_user_role(request.user) != Role.STUDENT:
        raise PermissionDenied("Only students can view their personal registrations.")
    registrations = Registration.objects.filter(
        user=request.user,
    ).select_related('event').order_by('-created_at')
    return render(request, 'registrations/my_registrations.html', {
        'registrations': registrations,
        'current_time': timezone.now(),
    })


@login_required
def registration_detail_view(request, pk):
    registration = get_object_or_404(
        Registration.objects.select_related('event', 'user'),
        pk=pk,
    )
    role = _get_user_role(request.user)
    if role == Role.STUDENT:
        if registration.user_id != request.user.pk:
            raise PermissionDenied("You can only view your own registrations.")
    elif role == Role.ORGANISER:
        if registration.event.organiser_id != request.user.pk:
            raise PermissionDenied("You can only view registrations for your own events.")
    elif role != Role.ADMIN:
        raise PermissionDenied("You do not have permission to view this registration.")

    can_cancel = (
        role == Role.STUDENT
        and registration.status == RegistrationStatus.REGISTERED
        and timezone.now() < registration.event.start_time
    )
    return render(request, 'registrations/registration_detail.html', {
        'registration': registration,
        'can_cancel': can_cancel,
    })


@student_required
def registration_success_view(request, pk):
    if _get_user_role(request.user) != Role.STUDENT:
        raise PermissionDenied("This confirmation is only available to the registered student.")
    registration = get_object_or_404(
        Registration.objects.select_related('event'),
        pk=pk,
        user=request.user,
        status=RegistrationStatus.REGISTERED,
    )
    return render(request, 'registrations/registration_success.html', {
        'registration': registration,
    })


@login_required
def event_participants_view(request, event_id):
    event = get_object_or_404(Event.objects.select_related('organiser'), pk=event_id)
    role = _get_user_role(request.user)
    is_admin = role == Role.ADMIN
    if not (is_admin or (role == Role.ORGANISER and event.organiser_id == request.user.pk)):
        raise PermissionDenied("You do not have permission to view registrations for this event.")

    all_registrations = _event_registration_queryset(event)
    counts = _registration_counts(all_registrations)
    registrations, search_query, selected_status = _registration_list_filters(
        all_registrations,
        request,
    )
    paginator = Paginator(registrations.order_by('created_at'), 25)
    page_obj = paginator.get_page(request.GET.get('page'))
    available_seats = (
        max(0, event.max_participants - counts['registered'])
        if event.max_participants is not None
        else None
    )
    return render(request, 'registrations/event_participants.html', {
        'event': event,
        'registrations': page_obj.object_list,
        'page_obj': page_obj,
        'counts': counts,
        'available_seats': available_seats,
        'search_query': search_query,
        'selected_status': selected_status,
        'status_choices': RegistrationStatus.choices,
        'is_admin': is_admin,
    })


@login_required
def export_event_participants_csv_view(request, event_id):
    event = get_object_or_404(Event.objects.select_related('organiser'), pk=event_id)
    role = _get_user_role(request.user)
    if not (
        role == Role.ADMIN
        or (role == Role.ORGANISER and event.organiser_id == request.user.pk)
    ):
        raise PermissionDenied("You do not have permission to export registrations for this event.")

    registrations, _, _ = _registration_list_filters(
        _event_registration_queryset(event).order_by('created_at'),
        request,
    )
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="event-{event.pk}-registrations.csv"'
    writer = csv.writer(response)
    writer.writerow(['Student name', 'Username', 'Email', 'Status', 'Registration date'])

    def safe_csv_value(value):
        value = str(value or '')
        if value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value
        return value

    for registration in registrations:
        writer.writerow([
            safe_csv_value(registration.user.get_full_name() or registration.user.username),
            safe_csv_value(registration.user.username),
            safe_csv_value(registration.user.email),
            registration.get_status_display(),
            registration.created_at.isoformat(),
        ])
    return response


@admin_required
def admin_registration_list_view(request):
    registrations = Registration.objects.select_related(
        'event',
        'user',
    ).order_by('-created_at')
    event_filter = request.GET.get('event', '').strip()
    if event_filter.isdigit():
        registrations = registrations.filter(event_id=int(event_filter))
    registrations, search_query, selected_status = _registration_list_filters(
        registrations,
        request,
    )
    page_obj = Paginator(registrations, 25).get_page(request.GET.get('page'))
    return render(request, 'registrations/admin_registration_list.html', {
        'page_obj': page_obj,
        'registrations': page_obj.object_list,
        'events': Event.objects.order_by('title'),
        'selected_event': event_filter,
        'search_query': search_query,
        'selected_status': selected_status,
        'status_choices': RegistrationStatus.choices,
    })


@admin_required
def admin_registration_detail_view(request, pk):
    if request.method not in ('GET', 'POST'):
        return HttpResponseNotAllowed(['GET', 'POST'])
    existing = get_object_or_404(Registration.objects.only('pk', 'event_id'), pk=pk)
    if request.method == 'POST':
        form = RegistrationAdminStatusForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                event = get_object_or_404(
                    Event.objects.select_for_update(),
                    pk=existing.event_id,
                )
                registration = get_object_or_404(
                    Registration.objects.select_for_update(),
                    pk=pk,
                )
                target_status = form.cleaned_data['status']
                now = timezone.now()
                if registration.status == target_status:
                    messages.info(request, "The registration already has that status.")
                elif target_status == RegistrationStatus.REGISTERED and (
                    event.status != EventStatus.PUBLISHED
                    or event.start_time <= now
                    or (
                        event.registration_deadline
                        and event.registration_deadline <= now
                    )
                ):
                    messages.error(
                        request,
                        "This registration cannot be activated because registration is closed for the event.",
                    )
                elif (
                    target_status == RegistrationStatus.REGISTERED
                    and registration.status != RegistrationStatus.REGISTERED
                    and event.max_participants is not None
                    and Registration.objects.filter(
                        event=event,
                        status=RegistrationStatus.REGISTERED,
                    ).exclude(pk=registration.pk).count() >= event.max_participants
                ):
                    messages.error(request, "This event has no available seats.")
                else:
                    registration.status = target_status
                    registration.save(update_fields=['status', 'updated_at'])
                    messages.success(request, "Registration status updated.")
            return redirect('registrations:admin_detail', pk=pk)
    else:
        form = None

    registration = get_object_or_404(
        Registration.objects.select_related('event', 'user', 'attendance'),
        pk=pk,
    )
    return render(request, 'registrations/admin_registration_detail.html', {
        'registration': registration,
        'form': form or RegistrationAdminStatusForm(initial={'status': registration.status}),
    })
