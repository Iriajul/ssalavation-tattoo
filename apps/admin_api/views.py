# apps/admin_api/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken

User = get_user_model()


class AdminLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from .serializers import CustomTokenObtainPairSerializer
        serializer = CustomTokenObtainPairSerializer(data=request.data)
        if serializer.is_valid():
            return Response(serializer.validated_data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from .serializers import ForgotPasswordSerializer
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "No admin account found with this email."}, 
                          status=status.HTTP_400_BAD_REQUEST)

        # Generate OTP
        otp = user.set_reset_otp()

        # Send email
        try:
            send_mail(
                subject="Salvation Tattoo Admin Password Reset Code",
                message=f"Your 5-digit reset code is: {otp}\n\nThis code will expire in 10 minutes.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Email sending failed: {e}")

        # Generate short-lived temp token (15 minutes)
        refresh = RefreshToken.for_user(user)
        refresh.access_token.set_exp(lifetime=timedelta(minutes=15))

        return Response({
            "message": "Reset code sent to your email.",
            "temp_token": str(refresh.access_token)     
        }, status=status.HTTP_200_OK)


class VerifyResetOTPView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from .serializers import VerifyResetOTPSerializer
        serializer = VerifyResetOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        temp_token = serializer.validated_data['temp_token']
        otp = serializer.validated_data['otp']

        try:
            untyped_token = UntypedToken(temp_token)
            user_id = untyped_token.payload.get('user_id')
            user = User.objects.get(id=user_id)
        except (InvalidToken, User.DoesNotExist, KeyError, Exception):
            return Response({"error": "Invalid or expired temporary token"}, 
                          status=status.HTTP_401_UNAUTHORIZED)

        if not user.verify_reset_otp(otp):
            return Response({"error": "Invalid or expired OTP"}, 
                          status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "message": "OTP verified successfully. You can now set a new password."
        }, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from .serializers import ResetPasswordSerializer
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        temp_token = serializer.validated_data['temp_token']
        new_password = serializer.validated_data['new_password']

        try:
            untyped_token = UntypedToken(temp_token)
            user_id = untyped_token.payload.get('user_id')
            user = User.objects.get(id=user_id)
        except (InvalidToken, User.DoesNotExist, KeyError, Exception):
            return Response({"error": "Invalid or expired temporary token"}, 
                          status=status.HTTP_401_UNAUTHORIZED)

        user.set_password(new_password)
        user.save(update_fields=['password'])

        return Response({
            "message": "Password reset successfully. Please login with your new password."
        }, status=status.HTTP_200_OK)