# apps/users/views.py
from rest_framework import filters, status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from apps.admin_api.models import Attendance, QRSession, Task, UserWorkSchedule

from .serializers import (
    AppLoginSerializer,
    AppTaskDetailSerializer,
    AppTaskListSerializer,
    VerifyLoginOTPSerializer,
    ResendLoginOTPSerializer,
    AppForgotPasswordSerializer,
    AppVerifyResetOTPSerializer,
    AppResetPasswordSerializer,
    AppUserSerializer,
)

EMPLOYEE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_temp_token(user, minutes=10):
    """Short-lived token to carry user identity between OTP steps"""
    refresh = RefreshToken.for_user(user)
    refresh.access_token.set_exp(lifetime=timedelta(minutes=minutes))
    return str(refresh.access_token)


def get_user_from_temp_token(temp_token):
    """Decode temp token and return user"""
    untyped_token = UntypedToken(temp_token)
    user_id       = untyped_token.payload.get('user_id')
    return User.objects.get(id=user_id)


def send_otp_email(email, otp, subject="Salvation Tattoo — Login Code"):
    try:
        send_mail(
            subject=subject,
            message=f"Your 5-digit code is: {otp}\n\nThis code will expire in 10 minutes.\n\nIf you didn't request this, please ignore.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as e:
        print(f"Email sending failed: {e}")


# ================================================================
# STEP 1 — LOGIN (validates credentials → sends OTP)
# ================================================================

class AppLoginView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AppLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        otp  = user.set_login_otp()

        send_otp_email(user.email, otp, subject="Salvation Tattoo — Login Code")

        return Response({
            "message":    "A verification code has been sent to your email.",
            "email":      user.email,
            "temp_token": get_temp_token(user, minutes=10),
        }, status=status.HTTP_200_OK)


# ================================================================
# STEP 2 — VERIFY LOGIN OTP (→ returns full JWT tokens)
# ================================================================

class VerifyLoginOTPView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = VerifyLoginOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token = serializer.validated_data['temp_token']
        otp        = serializer.validated_data['otp']

        try:
            user = get_user_from_temp_token(temp_token)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired session. Please login again."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.verify_login_otp(otp):
            return Response(
                {"error": "Invalid or expired OTP."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Issue full JWT tokens
        refresh = RefreshToken.for_user(user)
        refresh['role']  = user.role
        refresh['email'] = user.email

        return Response({
            "message": "Login successful.",
            "user":    AppUserSerializer(user).data,
            "tokens": {
                "access":  str(refresh.access_token),
                "refresh": str(refresh),
            },
        }, status=status.HTTP_200_OK)


# ================================================================
# RESEND LOGIN OTP
# ================================================================

class ResendLoginOTPView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ResendLoginOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token = serializer.validated_data['temp_token']

        try:
            user = get_user_from_temp_token(temp_token)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired session. Please login again."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        otp = user.set_login_otp()
        send_otp_email(user.email, otp, subject="Salvation Tattoo — Login Code (Resent)")

        # Issue a fresh temp token with new 10min expiry
        return Response({
            "message":    "A new verification code has been sent to your email.",
            "temp_token": get_temp_token(user, minutes=10),
        }, status=status.HTTP_200_OK)


# ================================================================
# FORGOT PASSWORD — Send OTP
# ================================================================

class AppForgotPasswordView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AppForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        user  = User.objects.get(email=email)
        otp   = user.set_reset_otp()

        send_otp_email(
            user.email, otp,
            subject="Salvation Tattoo — Password Reset Code"
        )

        return Response({
            "message":    "A reset code has been sent to your email.",
            "email":      user.email,
            "temp_token": get_temp_token(user, minutes=15),
        }, status=status.HTTP_200_OK)


# ================================================================
# VERIFY RESET OTP
# ================================================================

class AppVerifyResetOTPView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AppVerifyResetOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token = serializer.validated_data['temp_token']
        otp        = serializer.validated_data['otp']

        try:
            user = get_user_from_temp_token(temp_token)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired session. Please try again."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.verify_reset_otp(otp):
            return Response(
                {"error": "Invalid or expired OTP."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Issue a fresh temp token for reset password step
        return Response({
            "message":    "OTP verified. You can now reset your password.",
            "temp_token": get_temp_token(user, minutes=15),
        }, status=status.HTTP_200_OK)


# ================================================================
# RESET PASSWORD
# ================================================================

class AppResetPasswordView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AppResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token   = serializer.validated_data['temp_token']
        new_password = serializer.validated_data['new_password']

        try:
            user = get_user_from_temp_token(temp_token)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired session. Please try again."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        user.set_password(new_password)
        user.save(update_fields=['password'])

        return Response({
            "message": "Password reset successfully. Please login with your new password.",
        }, status=status.HTTP_200_OK)
    



# ================================================================
# APP — ATTENDANCE (Check In / Check Out)
# ================================================================

class AppCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user  = request.user
        token = request.data.get('token')

        # ── Role check ────────────────────────────────────────────
        if user.role not in EMPLOYEE_ROLES:
            return Response(
                {"error": "Only employees can check in."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Token required ────────────────────────────────────────
        if not token:
            return Response(
                {"error": "QR token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Validate QR session ───────────────────────────────────
        try:
            qr_session = QRSession.objects.select_related('location').get(
                token=token,
                is_active=True
            )
        except QRSession.DoesNotExist:
            return Response(
                {"error": "Invalid or expired QR code. Please ask your manager to regenerate."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Check if QR is expired ────────────────────────────────
        if qr_session.is_expired:
            qr_session.is_active = False
            qr_session.save(update_fields=['is_active'])
            return Response(
                {"error": "QR code has expired. Please ask your manager to regenerate."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Employee must belong to this location ─────────────────
        if user.location != qr_session.location:
            return Response(
                {"error": "This QR code is not for your location."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Check already checked in today ────────────────────────
        today = timezone.localdate()
        existing = Attendance.objects.filter(user=user, date=today).first()

        if existing:
            if existing.clock_in:
                return Response(
                    {"error": "You have already checked in today."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ── Determine status: present or late ─────────────────────
        now          = timezone.localtime()
        today_day    = now.strftime('%a').lower()[:3]  # 'mon', 'tue' etc
        clock_in_time = now.time()

        attendance_status = 'present'

        schedule = UserWorkSchedule.objects.filter(
            user       = user,
            day        = today_day,
            is_active  = True
        ).first()

        if schedule and schedule.start_time:
            if clock_in_time > schedule.start_time:
                attendance_status = 'late'

        # ── Create attendance record ──────────────────────────────
        attendance, _ = Attendance.objects.update_or_create(
            user = user,
            date = today,
            defaults={
                'location':   qr_session.location,
                'qr_session': qr_session,
                'clock_in':   clock_in_time,
                'status':     attendance_status,
            }
        )

        return Response({
            "message":       "Checked in successfully.",
            "status":        attendance_status,
            "clock_in":      clock_in_time.strftime('%I:%M %p'),
            "date":          str(today),
            "location_name": qr_session.location.name,
        }, status=status.HTTP_200_OK)


class AppCheckOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user  = request.user
        token = request.data.get('token')

        # ── Role check ────────────────────────────────────────────
        if user.role not in EMPLOYEE_ROLES:
            return Response(
                {"error": "Only employees can check out."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Token required ────────────────────────────────────────
        if not token:
            return Response(
                {"error": "QR token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Validate QR session ───────────────────────────────────
        try:
            qr_session = QRSession.objects.select_related('location').get(
                token=token,
                is_active=True
            )
        except QRSession.DoesNotExist:
            return Response(
                {"error": "Invalid or expired QR code. Please ask your manager to regenerate."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Check if QR is expired ────────────────────────────────
        if qr_session.is_expired:
            qr_session.is_active = False
            qr_session.save(update_fields=['is_active'])
            return Response(
                {"error": "QR code has expired. Please ask your manager to regenerate."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Employee must belong to this location ─────────────────
        if user.location != qr_session.location:
            return Response(
                {"error": "This QR code is not for your location."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Must have checked in first ────────────────────────────
        today = timezone.localdate()
        attendance = Attendance.objects.filter(
            user=user,
            date=today
        ).first()

        if not attendance or not attendance.clock_in:
            return Response(
                {"error": "You haven't checked in yet today."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Already checked out ───────────────────────────────────
        if attendance.clock_out:
            return Response(
                {"error": "You have already checked out today."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Save checkout time ────────────────────────────────────
        now            = timezone.localtime()
        clock_out_time = now.time()

        attendance.clock_out = clock_out_time
        attendance.save(update_fields=['clock_out'])

        return Response({
            "message":       "Checked out successfully.",
            "clock_in":      attendance.clock_in.strftime('%I:%M %p'),
            "clock_out":     clock_out_time.strftime('%I:%M %p'),
            "date":          str(today),
            "location_name": qr_session.location.name,
        }, status=status.HTTP_200_OK)


class AppTodayAttendanceView(APIView):
    """Get today's attendance status for home screen"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user  = request.user
        today = timezone.localdate()

        attendance = Attendance.objects.filter(
            user=user,
            date=today
        ).first()

        if not attendance:
            return Response({
                "date":       str(today),
                "status":     "not_checked_in",
                "clock_in":   None,
                "clock_out":  None,
                "location":   user.location.name if user.location else None,
            }, status=status.HTTP_200_OK)

        return Response({
            "date":       str(today),
            "status":     attendance.status if not attendance.clock_out else "checked_out",
            "clock_in":   attendance.clock_in.strftime('%I:%M %p') if attendance.clock_in else None,
            "clock_out":  attendance.clock_out.strftime('%I:%M %p') if attendance.clock_out else None,
            "location":   attendance.location.name,
        }, status=status.HTTP_200_OK)



class AppTaskViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['title', 'description']

    def get_queryset(self):
        user     = self.request.user
        queryset = Task.objects.filter(
            assigned_to=user
        ).select_related(
            'created_by', 'location',
            'completed_by', 'approved_by', 'rejected_by'
        ).order_by('-created_at')

        # ── Status filter ─────────────────────────────────────────
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AppTaskDetailSerializer
        return AppTaskListSerializer

    def list(self, request, *args, **kwargs):
        user     = request.user
        queryset = self.filter_queryset(self.get_queryset())

        # ── Stats ─────────────────────────────────────────────────
        all_tasks = Task.objects.filter(assigned_to=user)
        stats = {
            'total':    all_tasks.count(),
            'pending':  all_tasks.filter(status='pending').count(),
            'approved': all_tasks.filter(status='approved').count(),
            'rejected': all_tasks.filter(status='rejected').count(),
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer     = self.get_serializer(page, many=True)
            paginated_data = self.get_paginated_response(serializer.data)
            return Response({
                'stats': stats,
                'tasks': paginated_data.data,
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'stats': stats,
            'tasks': serializer.data,
        }, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        task = self.get_object()
        return Response(
            AppTaskDetailSerializer(task).data,
            status=status.HTTP_200_OK
        )

    @action(
        detail=True,
        methods=['post'],
        url_path='complete',
        parser_classes=[MultiPartParser, FormParser, JSONParser]
    )
    def complete(self, request, pk=None):
        task = self.get_object()
        user = request.user

        # ── Only assigned employee can complete ───────────────────
        if task.assigned_to != user:
            return Response(
                {"error": "You can only complete tasks assigned to you."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Only pending or rejected tasks can be completed ───────
        if task.status not in ['pending', 'rejected']:
            return Response(
                {"error": "Only pending or rejected tasks can be completed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Photo required check ──────────────────────────────────
        if task.requires_photo:
            photo = request.FILES.get('photo')
            if not photo:
                return Response(
                    {"error": "A photo is required to complete this task."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # ── Upload to Cloudinary ──────────────────────────────
            import cloudinary.uploader
            result        = cloudinary.uploader.upload(
                photo,
                folder='task_photos/'
            )
            task.photo_url = result['secure_url']

        # ── Mark as completed ─────────────────────────────────────
        task.status       = 'completed'
        task.completed_by = user
        task.completed_at = timezone.now()
        task.save(update_fields=[
            'status', 'completed_by', 'completed_at', 'photo_url'
        ])

        # ── Log activity ──────────────────────────────────────────
        from apps.admin_api.models import ActivityLog
        ActivityLog.objects.create(
            action      = 'task_completed',
            actor       = user,
            task        = task,
            target_user = user,
            message     = f'{user.get_full_name()} completed "{task.title}"'
        )

        return Response({
            "message":  "Task submitted successfully.",
            "task_id":  task.id,
            "title":    task.title,
            "status":   task.status,
            "photo_url": task.photo_url,
        }, status=status.HTTP_200_OK)