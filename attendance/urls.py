from django.urls import path
from . import views

app_name = 'attendance'

urlpatterns = [
    path('', views.attendance_dashboard_view, name='dashboard'),
    path('history/', views.student_attendance_history_view, name='history'),
    path('events/<int:event_id>/', views.event_attendees_view, name='event_attendees'),
    path('events/<int:event_id>/report/', views.event_attendance_report_view, name='event_report'),
]
