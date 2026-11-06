from django import forms

from .models import RegistrationStatus


class RegistrationAdminStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=RegistrationStatus.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
