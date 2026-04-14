# apps/users/serializers.py
from apps.admin_api.models import Task
from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

# App roles allowed to login to mobile app
APP_ROLES = ['tattoo_artist', 'body_piercer', 'staff']


# ================================================================
# LOGIN
# ================================================================

class AppLoginSerializer(serializers.Serializer):
    """Step 1 — validate credentials and send OTP"""
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email    = data.get('email')
        password = data.get('password')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid email or password.")

        if not user.check_password(password):
            raise serializers.ValidationError("Invalid email or password.")

        if not user.is_active:
            raise serializers.ValidationError("Your account has been deactivated. Contact your manager.")
        
        if user.is_suspended:
            raise serializers.ValidationError("Your account has been suspended. Please contact your manager.")

        if user.role not in APP_ROLES:
            raise serializers.ValidationError("Access denied. You are not allowed to login to the app.")

        data['user'] = user
        return data


# ================================================================
# OTP VERIFICATION (Login)
# ================================================================

class VerifyLoginOTPSerializer(serializers.Serializer):
    """Step 2 — verify OTP to complete login"""
    temp_token = serializers.CharField(required=True)
    otp        = serializers.CharField(max_length=5, min_length=5, required=True)


class ResendLoginOTPSerializer(serializers.Serializer):
    """Resend login OTP"""
    temp_token = serializers.CharField(required=True)


# ================================================================
# FORGOT PASSWORD
# ================================================================

class AppForgotPasswordSerializer(serializers.Serializer):
    """Send reset OTP to email"""
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value, role__in=APP_ROLES, is_active=True).exists():
            raise serializers.ValidationError("No active account found with this email.")
        return value


# ================================================================
# VERIFY RESET OTP
# ================================================================

class AppVerifyResetOTPSerializer(serializers.Serializer):
    """Verify reset OTP"""
    temp_token = serializers.CharField(required=True)
    otp        = serializers.CharField(max_length=5, min_length=5, required=True)


# ================================================================
# RESET PASSWORD
# ================================================================

class AppResetPasswordSerializer(serializers.Serializer):
    """Set new password after OTP verified"""
    temp_token        = serializers.CharField(required=True)
    new_password      = serializers.CharField(min_length=8, write_only=True, required=True)
    confirm_password  = serializers.CharField(min_length=8, write_only=True, required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data


# ================================================================
# USER PROFILE RESPONSE
# ================================================================

class AppUserSerializer(serializers.ModelSerializer):
    """User data returned after successful login"""
    role_display  = serializers.CharField(source='get_role_display', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)

    class Meta:
        model  = User
        fields = [
            'id', 'first_name', 'last_name', 'username',
            'email', 'role', 'role_display', 'phone',
            'location', 'location_name', 'is_active',
        ]


class AppTaskListSerializer(serializers.ModelSerializer):
    assigned_by_name = serializers.SerializerMethodField()
    assigned_by_role = serializers.SerializerMethodField()
    due_date_display = serializers.SerializerMethodField()

    class Meta:
        model  = Task
        fields = [
            'id', 'title', 'status',
            'assigned_by_name', 'assigned_by_role',
            'due_date', 'due_date_display',
            'requires_photo', 'is_recurring', 'frequency',
        ]

    def get_assigned_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip()
        return None

    def get_assigned_by_role(self, obj):
        if not obj.created_by:
            return 'ADMIN'
        role_map = {
            'super_admin':      'ADMIN',
            'branch_manager':   'MGR',
            'district_manager': 'DM',
        }
        return role_map.get(obj.created_by.role, 'ADMIN')

    def get_due_date_display(self, obj):
        from django.utils import timezone
        today    = timezone.localdate()
        tomorrow = today + __import__('datetime').timedelta(days=1)
        if obj.due_date == today:
            return f"Today, {obj.due_date.strftime('%b %d, %Y')}"
        elif obj.due_date == tomorrow:
            return f"Tomorrow, {obj.due_date.strftime('%b %d, %Y')}"
        return obj.due_date.strftime('%b %d, %Y')


class AppTaskDetailSerializer(serializers.ModelSerializer):
    assigned_by_name = serializers.SerializerMethodField()
    assigned_by_role = serializers.SerializerMethodField()
    due_date_display = serializers.SerializerMethodField()

    class Meta:
        model  = Task
        fields = [
            'id', 'title', 'description', 'status',
            'assigned_by_name', 'assigned_by_role',
            'due_date', 'due_date_display',
            'requires_photo', 'photo_url',
            'is_recurring', 'frequency',
            'completed_at', 'rejection_reason',
        ]

    def get_assigned_by_name(self, obj):
        if obj.created_by:
            role = obj.created_by.role
            name = f"{obj.created_by.first_name} {obj.created_by.last_name}".strip()
            if role == 'branch_manager':
                return f"Manager — {name}"
            elif role == 'district_manager':
                return f"District Manager — {name}"
            return f"Admin — {name}"
        return "Admin"

    def get_assigned_by_role(self, obj):
        if not obj.created_by:
            return 'ADMIN'
        role_map = {
            'super_admin':      'ADMIN',
            'branch_manager':   'MGR',
            'district_manager': 'DM',
        }
        return role_map.get(obj.created_by.role, 'ADMIN')

    def get_due_date_display(self, obj):
        from django.utils import timezone
        import datetime
        today    = timezone.localdate()
        tomorrow = today + datetime.timedelta(days=1)
        if obj.due_date == today:
            return f"Today, {obj.due_date.strftime('%b %d, %Y')}"
        elif obj.due_date == tomorrow:
            return f"Tomorrow, {obj.due_date.strftime('%b %d, %Y')}"
        return obj.due_date.strftime('%b %d, %Y')
