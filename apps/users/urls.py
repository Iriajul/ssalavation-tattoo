from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    AppLoginView,
    AppPerformanceView,
    AppProfileView,
    VerifyLoginOTPView,
    ResendLoginOTPView,
    AppForgotPasswordView,
    AppVerifyResetOTPView,
    AppResetPasswordView,
    AppCheckInView,
    AppCheckOutView,
    AppTodayAttendanceView,
    AppTaskViewSet,
    AppTaskHistoryViewSet,
    AppInstructionViewSet,
)

router = DefaultRouter()
router.register('tasks', AppTaskViewSet, basename='app-tasks')
router.register('tasks-history', AppTaskHistoryViewSet, basename='app-tasks-history')
router.register('instructions', AppInstructionViewSet, basename='app-instructions')

urlpatterns = [
    # ── Auth ──────────────────────────────────────────────────────
    path('auth/login/',            AppLoginView.as_view(),          name='app-login'),
    path('auth/verify-login-otp/', VerifyLoginOTPView.as_view(),    name='app-verify-login-otp'),
    path('auth/resend-otp/',       ResendLoginOTPView.as_view(),    name='app-resend-otp'),
    path('auth/forgot-password/',  AppForgotPasswordView.as_view(), name='app-forgot-password'),
    path('auth/verify-reset-otp/', AppVerifyResetOTPView.as_view(), name='app-verify-reset-otp'),
    path('auth/reset-password/',   AppResetPasswordView.as_view(),  name='app-reset-password'),
    path('auth/token/refresh/',    TokenRefreshView.as_view(),      name='token-refresh'),
    # ── Attendance ────────────────────────────────────────────────
    path('attendance/checkin/',    AppCheckInView.as_view(),           name='app-checkin'),
    path('attendance/checkout/',   AppCheckOutView.as_view(),          name='app-checkout'),
    path('attendance/today/',      AppTodayAttendanceView.as_view(),   name='app-today-attendance'),
    # ── Tasks ─────────────────────────────────────────────────────
    path('', include(router.urls)),

    path('profile/',             AppProfileView.as_view(),     name='app-profile'),
    path('profile/performance/', AppPerformanceView.as_view(), name='app-performance'),
]