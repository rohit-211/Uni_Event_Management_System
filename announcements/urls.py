from django.urls import path
from . import views

app_name = 'announcements'

urlpatterns = [
    # Feed & Detail views
    path('', views.announcement_list_view, name='list'),
    path('<int:pk>/', views.announcement_detail_view, name='detail'),

    # Authoring & Management views
    path('create/', views.announcement_create_view, name='create'),
    path('<int:pk>/edit/', views.announcement_edit_view, name='edit'),
    path('<int:pk>/delete/', views.announcement_delete_view, name='delete'),
    path('<int:pk>/toggle-publish/', views.announcement_toggle_publish_view, name='toggle_publish'),
]
