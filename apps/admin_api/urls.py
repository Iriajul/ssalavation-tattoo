# apps/admin_api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AdminLoginView,
    ForgotPasswordView,
    VerifyResetOTPView,
    ResetPasswordView,
    LocationViewSet,
    UserViewSet,
    TaskViewSet,
    LocationEmployeesView,
    InstructionViewSet,
)

router = DefaultRouter()
router.register(r'locations',    LocationViewSet,    basename='location')
router.register(r'users',        UserViewSet,        basename='user')
router.register(r'tasks',        TaskViewSet,        basename='task')
router.register(r'instructions', InstructionViewSet, basename='instruction')

urlpatterns = [
    # ── Auth ──────────────────────────────────────────────────────
    path('login/',           AdminLoginView.as_view(),     name='admin-login'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('verify-otp/',      VerifyResetOTPView.as_view(), name='verify-otp'),
    path('reset-password/',  ResetPasswordView.as_view(),  name='reset-password'),

    # ── Employees by location ─────────────────────────────────────
    path('locations/<int:pk>/employees/', LocationEmployeesView.as_view(), name='location-employees'),

] + router.urls