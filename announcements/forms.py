from django import forms
from django.core.exceptions import ValidationError
from accounts.models import Role, get_or_create_profile
from .models import Announcement, Audience, Priority, Status


class AnnouncementForm(forms.ModelForm):
    """
    Form for creating and editing university announcements.
    Dynamically adjusts audience choices based on whether the logged-in user is an Admin or Organiser:
    - Administrators can target ALL, STUDENTS, or ORGANISERS.
    - Organisers are restricted to STUDENTS or ORGANISERS (cannot publish university-wide).
    """
    class Meta:
        model = Announcement
        fields = ['title', 'content', 'event_title', 'audience', 'priority', 'status']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter a clear announcement headline...'
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 6,
                'placeholder': 'Provide full details, important deadlines, or guidelines...'
            }),
            'event_title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Optional associated event name (e.g., Hackathon 2026)'
            }),
            'audience': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Enforce server-side role constraints on audience field
        if self.user:
            profile = get_or_create_profile(self.user)
            is_admin = self.user.is_superuser or (profile and profile.role == Role.ADMIN)

            if not is_admin:
                # Organisers cannot publish university-wide (Audience.ALL)
                allowed_choices = [
                    (Audience.STUDENTS, Audience.STUDENTS.label),
                    (Audience.ORGANISERS, Audience.ORGANISERS.label),
                ]
                self.fields['audience'].choices = allowed_choices
                self.fields['audience'].help_text = (
                    "Organisers may broadcast to Students or fellow Organisers. "
                    "University-wide notices require administrative privileges."
                )

    def clean_title(self):
        title = self.cleaned_data.get('title', '').strip()
        if len(title) < 5:
            raise ValidationError("The announcement title must be at least 5 characters long.")
        return title

    def clean_content(self):
        content = self.cleaned_data.get('content', '').strip()
        if len(content) < 10:
            raise ValidationError("The announcement content must be at least 10 characters long.")
        return content

    def clean_audience(self):
        audience = self.cleaned_data.get('audience')
        if self.user:
            profile = get_or_create_profile(self.user)
            is_admin = self.user.is_superuser or (profile and profile.role == Role.ADMIN)

            if not is_admin and audience == Audience.ALL:
                raise ValidationError(
                    "Security Notice: Organisers are not authorised to publish university-wide announcements. "
                    "Please choose 'Students Only' or 'Organisers Only'."
                )
        return audience
