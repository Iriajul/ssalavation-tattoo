# apps/admin_api/urls.py
from django.urls import path
from .views import (
    AdminLoginView,
    ForgotPasswordView,
    VerifyResetOTPView,      
    ResetPasswordView
)

urlpatterns = [
    path('login/', AdminLoginView.as_view(), name='admin-login'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('verify-otp/', VerifyResetOTPView.as_view(), name='verify-otp'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset-password'),
]