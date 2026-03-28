# apps/admin_api/serializers.py
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login Serializer"""
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user

        if user.role not in ['super_admin', 'district_manager', 'branch_manager']:
            raise serializers.ValidationError("Access denied. Invalid admin role.")

        data['user'] = {
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'role': user.role,
            'role_display': user.get_role_display(),
            'is_super_admin': user.is_super_admin(),
        }
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    """Forgot Password - Send OTP"""
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(
            email=value, 
            role__in=['super_admin', 'district_manager', 'branch_manager']
        ).exists():
            raise serializers.ValidationError("No admin account found with this email.")
        return value


class VerifyResetOTPSerializer(serializers.Serializer):
    """Verify OTP"""
    temp_token = serializers.CharField(required=True)
    otp = serializers.CharField(max_length=5, min_length=5, required=True)


class ResetPasswordSerializer(serializers.Serializer):
    """Reset Password"""
    temp_token = serializers.CharField(required=True)
    new_password = serializers.CharField(min_length=8, write_only=True, required=True)
    confirm_password = serializers.CharField(min_length=8, write_only=True, required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords do not match.")
        return data