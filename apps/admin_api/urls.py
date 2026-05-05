# apps/admin_api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .district_views import DistrictManagerDashboardView, DistrictManagerLocationsView, DistrictManagerReportsView, DistrictManagerTaskView, DistrictManagerTaskDetailView, DistrictManagerLocationEmployeesView, DistrictManagerVerificationActionView, DistrictManagerVerificationView,DistrictManagerProfileView, DistrictManagerChangePasswordView
from .views import (
    AdminChangePasswordView,
    AdminLoginView,
    AdminProfileView,
    BranchManagerDashboardView,
    BranchManagerProfileView,
    BranchManagerTaskViewSet,
    BranchManagerVerificationView,
    DashboardView,
    FAQViewSet,
    ForgotPasswordView,
    PerformanceAnalyticsView,
    # QRIntervalListView,
    # QRSessionDetailView,
    ReportsAnalyticsView,
    SplashScreenView,
    UserAttendanceView,
    VerifyResetOTPView,
    ResetPasswordView,
    LocationViewSet,
    UserViewSet,
    TaskViewSet,
    LocationEmployeesView,
    InstructionViewSet,
    # QRHistoryView,
    # QRCurrentView,
    # QRGenerateView,
    SuperAdminQRView,
    SuperAdminQRDetailView,
    SuperAdminQRIntervalListView,
    ClockInUserQRView,
    BranchManagerLocationEmployeesView,
    NotificationViewSet,
    BranchManagerReportsView,
    BranchManagerChangePasswordView,

)

router = DefaultRouter()
router.register(r'locations',    LocationViewSet,    basename='location')
router.register(r'users',        UserViewSet,        basename='user')
router.register(r'tasks',        TaskViewSet,        basename='task')
router.register(r'instructions', InstructionViewSet, basename='instruction')
router.register('app-content/faqs', FAQViewSet, basename='faqs')
router.register('manager/tasks', BranchManagerTaskViewSet, basename='manager-tasks')
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    # ── Auth ──────────────────────────────────────────────────────
    path('login/',           AdminLoginView.as_view(),     name='admin-login'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('verify-otp/',      VerifyResetOTPView.as_view(), name='verify-otp'),
    path('reset-password/',  ResetPasswordView.as_view(),  name='reset-password'),
    path('profile/',          AdminProfileView.as_view(),        name='admin-profile'),
    path('profile/password/', AdminChangePasswordView.as_view(), name='admin-change-password'),
    path('performance/', PerformanceAnalyticsView.as_view(), name='performance-analytics'),
    path('reports/', ReportsAnalyticsView.as_view(), name='reports-analytics'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    # ── Branch Manager — QR Attendance ────────────────────────────
    path('branch-manager/dashboard/', BranchManagerDashboardView.as_view(), name='branch-manager-dashboard'),
    path('branch-manager/profile/', BranchManagerProfileView.as_view(), name='branch-manager-profile'),
    path('branch-manager/reports/', BranchManagerReportsView.as_view(), name='branch-manager-reports'),
    path('branch-manager/profile/password/', BranchManagerChangePasswordView.as_view(), name='branch-manager-change-password'),
    #── Super Admin QR ────────────────────────────────────────────
    path('qr/intervals/',          SuperAdminQRIntervalListView.as_view(), name='qr-intervals'),   
    path('qr/<int:pk>/details/',   SuperAdminQRDetailView.as_view(),       name='super-admin-qr-details'),
    path('qr/',                    SuperAdminQRView.as_view(),              name='super-admin-qr'),

    # ── Clock In User QR ──────────────────────────────────────────
    path('clock-in/qr/',           ClockInUserQRView.as_view(),         name='clock-in-user-qr'),

    # path('manager/qr/generate/',        QRGenerateView.as_view(),      name='qr-generate'),
    # path('manager/qr/current/',         QRCurrentView.as_view(),       name='qr-current'),
    # path('manager/qr/history/',         QRHistoryView.as_view(),       name='qr-history'),
    # path('manager/qr/<int:pk>/details/', QRSessionDetailView.as_view(), name='qr-details'),
    # path('manager/qr/intervals/', QRIntervalListView.as_view(), name='qr-intervals'),
    path('manager/employees/', BranchManagerLocationEmployeesView.as_view(), name='manager-employees'),
    path('manager/verifications/', BranchManagerVerificationView.as_view(), name='manager-verifications'),
    path('users-attendance/', UserAttendanceView.as_view(), name='users-attendance'),
    # ── Employees by location ─────────────────────────────────────
    path('locations/<int:pk>/employees/', LocationEmployeesView.as_view(), name='location-employees'),
    path('app-content/splash-screen/', SplashScreenView.as_view(), name='splash-screen'),
    path('district-manager/dashboard/', DistrictManagerDashboardView.as_view(), name='district-manager-dashboard'),
    path('district-manager/tasks/',                            DistrictManagerTaskView.as_view(),              name='district-manager-tasks'),
    path('district-manager/tasks/<int:pk>/',                   DistrictManagerTaskDetailView.as_view(),        name='district-manager-task-detail'),
    path('district-manager/locations/<int:pk>/employees/',     DistrictManagerLocationEmployeesView.as_view(), name='district-manager-location-employees'),
    path('district-manager/verifications/',DistrictManagerVerificationView.as_view(),name='district-manager-verifications'),
    path('district-manager/verifications/<int:pk>/<str:action>/',DistrictManagerVerificationActionView.as_view(),name='district-manager-verification-action'),
    path('district/reports/', DistrictManagerReportsView.as_view(), name='district-reports'),
    path('district-manager/profile/',          DistrictManagerProfileView.as_view(),         name='district-manager-profile'),
    path('district-manager/profile/password/', DistrictManagerChangePasswordView.as_view(),  name='district-manager-change-password'),
    path('district-manager/locations/', DistrictManagerLocationsView.as_view(), name='district-manager-locations'),

] + router.urls