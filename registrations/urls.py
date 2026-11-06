from django.urls import path
from . import views

app_name = 'registrations'

urlpatterns = [
    path('', views.my_registrations_view, name='my_registrations'),
    path('manage/', views.admin_registration_list_view, name='manage'),
    path('manage/<int:pk>/', views.admin_registration_detail_view, name='admin_detail'),
    path('events/<int:event_id>/export/', views.export_event_participants_csv_view, name='export'),
    path('events/<int:event_id>/register/', views.register_for_event_view, name='register'),
    path('events/<int:event_id>/cancel/', views.cancel_registration_view, name='cancel'),
    path('events/<int:event_id>/participants/', views.event_participants_view, name='participants'),
    path('<int:pk>/success/', views.registration_success_view, name='success'),
    path('<int:pk>/', views.registration_detail_view, name='detail'),
]
