from django import forms

from .models import AttendanceStatus


class AttendanceMarkForm(forms.Form):
    registration_id = forms.IntegerField(widget=forms.HiddenInput)
    status = forms.ChoiceField(
        choices=AttendanceStatus.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
