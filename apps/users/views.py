# apps/users/views.py
from rest_framework import status
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

from apps.admin_api.models import Attendance, QRSession, UserWorkSchedule

from .serializers import (
    AppLoginSerializer,
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
