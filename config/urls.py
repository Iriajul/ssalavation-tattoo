# config/urls.py
from django.contrib import admin
from django.urls import path, include
 
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/admin/', include('apps.admin_api.urls')),  # super admin dashboard
    path('api/users/', include('apps.users.urls')),       # mobile app users
]
 