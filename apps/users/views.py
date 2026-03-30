# apps/users/views.py
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken

from .serializers import (
    AppLoginSerializer,
    VerifyLoginOTPSerializer,
    ResendLoginOTPSerializer,
    AppForgotPasswordSerializer,
    AppVerifyResetOTPSerializer,
    AppResetPasswordSerializer,
    AppUserSerializer,
)

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