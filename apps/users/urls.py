from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView  
from .views import (
    AppLoginView,
    VerifyLoginOTPView,
    ResendLoginOTPView,
    AppForgotPasswordView,
    AppVerifyResetOTPView,
    AppResetPasswordView,
)

urlpatterns = [
    # ── Login flow ────────────────────────────────────────────────
    path('auth/login/',            AppLoginView.as_view(),          name='app-login'),
    path('auth/verify-login-otp/', VerifyLoginOTPView.as_view(),    name='app-verify-login-otp'),
    path('auth/resend-otp/',       ResendLoginOTPView.as_view(),    name='app-resend-otp'),
    # ── Forgot / Reset password flow ──────────────────────────────
    path('auth/forgot-password/',  AppForgotPasswordView.as_view(), name='app-forgot-password'),
    path('auth/verify-reset-otp/', AppVerifyResetOTPView.as_view(), name='app-verify-reset-otp'),
    path('auth/reset-password/',   AppResetPasswordView.as_view(),  name='app-reset-password'),
    # ── Token refresh ─────────────────────────────────────────────
    path('auth/token/refresh/',    TokenRefreshView.as_view(),      name='token-refresh'), 
]