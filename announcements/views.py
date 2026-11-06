from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.contrib import messages
from django.db.models import Q, Case, When, IntegerField
from django.urls import reverse

from accounts.models import Role, get_or_create_profile
from .models import Announcement, Audience, Priority, Status
from .forms import AnnouncementForm


def get_user_role(user):
    """
    Helper utility to resolve user's application role safely.
    Returns: Role string ('ADMIN', 'ORGANISER', 'STUDENT') or None if unauthenticated.
    """
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return Role.ADMIN
    profile = get_or_create_profile(user)
    return profile.role if profile else Role.STUDENT


def announcement_list_view(request):
    """
    Displays the announcement feed tailored to the user's role:
    - Anonymous: Published university-wide notices only.
    - Student: Published university-wide and student-targeted notices.
    - Organiser: Published university-wide and organiser notices, plus their own authored drafts.
    - Admin: All announcements across all audiences and statuses.
    """
    user_role = get_user_role(request.user)
    is_admin = (user_role == Role.ADMIN)
    is_organiser = (user_role == Role.ORGANISER)
    can_create = is_admin or is_organiser

    queryset = Announcement.objects.select_related('creator').all()

    # Apply strict role-based visibility rules
    if is_admin:
        # Administrators see all announcements
        pass
    elif is_organiser:
        # Organisers see public/organiser announcements, plus their own drafts
        queryset = queryset.filter(
            Q(status=Status.PUBLISHED, audience__in=[Audience.ALL, Audience.ORGANISERS]) |
            Q(creator=request.user)
        )
    elif user_role == Role.STUDENT:
        # Students see published ALL and STUDENTS notices
        queryset = queryset.filter(
            status=Status.PUBLISHED,
            audience__in=[Audience.ALL, Audience.STUDENTS]
        )
    else:
        # Unauthenticated public visitors see only published ALL notices
        queryset = queryset.filter(
            status=Status.PUBLISHED,
            audience=Audience.ALL
        )

    # Search filter (title, content, or related event title)
    search_query = request.GET.get('q', '').strip()
    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query) |
            Q(content__icontains=search_query) |
            Q(event_title__icontains=search_query)
        )

    # Priority filter
    selected_priority = request.GET.get('priority', '').strip()
    if selected_priority in Priority.values:
        queryset = queryset.filter(priority=selected_priority)

    # Audience filter (within user's allowed visibility scope)
    selected_audience = request.GET.get('audience', '').strip()
    if selected_audience in Audience.values:
        queryset = queryset.filter(audience=selected_audience)

    # Status filter (available to admins and organisers)
    selected_status = request.GET.get('status', '').strip()
    if can_create and selected_status in Status.values:
        queryset = queryset.filter(status=selected_status)

    # Order by priority weight (URGENT > IMPORTANT > NORMAL), then newest first
    priority_weight = Case(
        When(priority=Priority.URGENT, then=1),
        When(priority=Priority.IMPORTANT, then=2),
        When(priority=Priority.NORMAL, then=3),
        default=4,
        output_field=IntegerField(),
    )
    queryset = queryset.order_by(priority_weight, '-created_at')

    # Pagination: 8 items per page
    paginator = Paginator(queryset, 8)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'announcements': page_obj.object_list,
        'is_admin': is_admin,
        'is_organiser': is_organiser,
        'can_create': can_create,
        'search_query': search_query,
        'selected_priority': selected_priority,
        'selected_audience': selected_audience,
        'selected_status': selected_status,
        'priorities': Priority.choices,
        'audiences': Audience.choices,
        'statuses': Status.choices,
        'total_count': paginator.count,
    }
    return render(request, 'announcements/announcement_list.html', context)


def announcement_detail_view(request, pk):
    """
    Displays full details of a specific announcement with role authorization checks.
    """
    announcement = get_object_or_404(Announcement.objects.select_related('creator'), pk=pk)
    user_role = get_user_role(request.user)
    is_admin = (user_role == Role.ADMIN)
    is_organiser = (user_role == Role.ORGANISER)
    is_creator = (request.user.is_authenticated and announcement.creator == request.user)

    # 1. Draft Access Check
    if announcement.status == Status.DRAFT:
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        if not (is_admin or is_creator):
            raise PermissionDenied("Draft announcements are only accessible to the author or system administrators.")

    # 2. Audience Target Check for published announcements
    if announcement.status == Status.PUBLISHED and not is_admin and not is_creator:
        if announcement.audience == Audience.STUDENTS:
            if not request.user.is_authenticated:
                return redirect(f"{reverse('accounts:login')}?next={request.path}")
            if user_role == Role.ORGANISER:
                raise PermissionDenied("This announcement is targeted specifically to students.")
        elif announcement.audience == Audience.ORGANISERS:
            if not request.user.is_authenticated:
                return redirect(f"{reverse('accounts:login')}?next={request.path}")
            if user_role == Role.STUDENT:
                raise PermissionDenied("This announcement is targeted specifically to event organisers.")

    # 3. Action permissions
    can_edit = is_admin or (is_organiser and is_creator)
    can_delete = can_edit

    context = {
        'announcement': announcement,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'is_admin': is_admin,
    }
    return render(request, 'announcements/announcement_detail.html', context)


@login_required
def announcement_create_view(request):
    """
    Create a new announcement.
    Restricted to Admins and Organisers. Students are strictly barred with HTTP 403.
    """
    user_role = get_user_role(request.user)
    if user_role == Role.STUDENT:
        raise PermissionDenied("Students do not possess permissions to publish campus announcements.")

    if request.method == 'POST':
        form = AnnouncementForm(request.POST, user=request.user)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.creator = request.user
            announcement.save()
            messages.success(request, f"Announcement '{announcement.title}' created successfully!")
            return redirect('announcements:detail', pk=announcement.pk)
        else:
            messages.error(request, "Please correct the errors in the announcement form.")
    else:
        form = AnnouncementForm(user=request.user)

    context = {
        'form': form,
        'is_edit': False,
    }
    return render(request, 'announcements/announcement_form.html', context)


@login_required
def announcement_edit_view(request, pk):
    """
    Edit an existing announcement.
    Admins can edit any announcement. Organisers can edit only announcements they created.
    Students cannot edit any announcement.
    """
    announcement = get_object_or_404(Announcement, pk=pk)
    user_role = get_user_role(request.user)
    is_admin = (user_role == Role.ADMIN)
    is_creator = (announcement.creator == request.user)

    if not (is_admin or (user_role == Role.ORGANISER and is_creator)):
        raise PermissionDenied("You do not have permission to modify this announcement.")

    if request.method == 'POST':
        form = AnnouncementForm(request.POST, instance=announcement, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Announcement '{announcement.title}' updated successfully.")
            return redirect('announcements:detail', pk=announcement.pk)
        else:
            messages.error(request, "Please correct the form errors below.")
    else:
        form = AnnouncementForm(instance=announcement, user=request.user)

    context = {
        'form': form,
        'announcement': announcement,
        'is_edit': True,
    }
    return render(request, 'announcements/announcement_form.html', context)


@login_required
def announcement_delete_view(request, pk):
    """
    Delete an announcement with confirmation.
    Protected against unauthorized deletion by students or non-author organisers.
    """
    announcement = get_object_or_404(Announcement, pk=pk)
    user_role = get_user_role(request.user)
    is_admin = (user_role == Role.ADMIN)
    is_creator = (announcement.creator == request.user)

    if not (is_admin or (user_role == Role.ORGANISER and is_creator)):
        raise PermissionDenied("You do not have permission to delete this announcement.")

    if request.method == 'POST':
        title = announcement.title
        announcement.delete()
        messages.success(request, f"Announcement '{title}' was permanently deleted.")
        return redirect('announcements:list')

    return render(request, 'announcements/announcement_confirm_delete.html', {
        'announcement': announcement
    })


@login_required
def announcement_toggle_publish_view(request, pk):
    """
    Quick POST action to toggle between DRAFT and PUBLISHED status.
    Requires Admin privileges or original author permissions.
    """
    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('announcements:detail', pk=pk)

    announcement = get_object_or_404(Announcement, pk=pk)
    user_role = get_user_role(request.user)
    is_admin = (user_role == Role.ADMIN)
    is_creator = (announcement.creator == request.user)

    if not (is_admin or (user_role == Role.ORGANISER and is_creator)):
        raise PermissionDenied("You do not have permission to publish or unpublish this announcement.")

    # Guard against Organisers publishing university-wide
    if announcement.status == Status.DRAFT and announcement.audience == Audience.ALL and not is_admin:
        raise PermissionDenied("Organisers cannot publish university-wide announcements.")

    if announcement.status == Status.PUBLISHED:
        announcement.status = Status.DRAFT
        announcement.save()
        messages.info(request, f"Announcement '{announcement.title}' has been moved to Drafts.")
    else:
        announcement.status = Status.PUBLISHED
        announcement.save()
        messages.success(request, f"Announcement '{announcement.title}' has been published successfully.")

    return redirect('announcements:detail', pk=announcement.pk)
