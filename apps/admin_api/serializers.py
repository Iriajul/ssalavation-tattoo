# apps/admin_api/serializers.py
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import Location, UserWorkSchedule, Task, Instruction

User = get_user_model()

# Roles that require a weekly schedule
SCHEDULE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']
ASSIGNABLE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']
VISIBILITY_ROLES = ['tattoo_artist', 'body_piercer', 'staff']

# ================================================================
# AUTH SERIALIZERS
# ================================================================

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user

        if user.role not in ['super_admin', 'district_manager', 'branch_manager']:
            raise serializers.ValidationError("Access denied. Invalid admin role.")

        data['user'] = {
            'id':             user.id,
            'email':          user.email,
            'username':       user.username,
            'role':           user.role,
            'role_display':   user.get_role_display(),
            'is_super_admin': user.is_super_admin(),
        }
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(
            email=value,
            role__in=['super_admin', 'district_manager', 'branch_manager']
        ).exists():
            raise serializers.ValidationError("No admin account found with this email.")
        return value


class VerifyResetOTPSerializer(serializers.Serializer):
    temp_token = serializers.CharField(required=True)
    otp        = serializers.CharField(max_length=5, min_length=5, required=True)


class ResetPasswordSerializer(serializers.Serializer):
    temp_token       = serializers.CharField(required=True)
    new_password     = serializers.CharField(min_length=8, write_only=True, required=True)
    confirm_password = serializers.CharField(min_length=8, write_only=True, required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords do not match.")
        return data


# ================================================================
# LOCATION SERIALIZERS
# ================================================================

class LocationSerializer(serializers.ModelSerializer):
    staff_count = serializers.IntegerField(read_only=True)

    class Meta:
        model  = Location
        fields = [
            'id', 'name', 'street_address', 'city_state',
            'status', 'staff_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'staff_count', 'created_at', 'updated_at']

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Studio name cannot be blank.")
        return value.strip()

    def validate_street_address(self, value):
        if not value.strip():
            raise serializers.ValidationError("Street address cannot be blank.")
        return value.strip()


class LocationListSerializer(serializers.ModelSerializer):
    staff_count = serializers.IntegerField(read_only=True)

    class Meta:
        model  = Location
        fields = ['id', 'name', 'street_address', 'city_state', 'status', 'staff_count']


class LocationStatsSerializer(serializers.Serializer):
    total_locations  = serializers.IntegerField()
    total_staff      = serializers.IntegerField()
    active_locations = serializers.IntegerField()


# ================================================================
# WORK SCHEDULE SERIALIZERS
# ================================================================

class WorkScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model  = UserWorkSchedule
        fields = ['id', 'day', 'is_active', 'start_time', 'end_time']

    def validate(self, data):
        if data.get('is_active'):
            if not data.get('start_time'):
                raise serializers.ValidationError({"start_time": "Start time is required when day is active."})
            if not data.get('end_time'):
                raise serializers.ValidationError({"end_time": "End time is required when day is active."})
            if data['start_time'] >= data['end_time']:
                raise serializers.ValidationError({"end_time": "End time must be after start time."})
        return data


# ================================================================
# USER SERIALIZERS
# ================================================================

class UserListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for user list table"""
    role_display  = serializers.CharField(source='get_role_display', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
    joined        = serializers.DateTimeField(source='date_joined', format='%b %d, %Y', read_only=True)

    class Meta:
        model  = User
        fields = [
            'id', 'first_name', 'last_name', 'username',
            'email', 'role', 'role_display',
            'location', 'location_name',
            'is_active', 'joined',
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    """Full user detail with work schedule"""
    role_display   = serializers.CharField(source='get_role_display', read_only=True)
    location_name  = serializers.CharField(source='location.name', read_only=True)
    work_schedules = WorkScheduleSerializer(many=True, read_only=True)

    class Meta:
        model  = User
        fields = [
            'id', 'first_name', 'last_name', 'username',
            'email', 'role', 'role_display', 'phone',
            'location', 'location_name',
            'is_active', 'date_joined',
            'work_schedules',
        ]


class UserCreateSerializer(serializers.ModelSerializer):
    """Create user with optional work schedule"""
    password       = serializers.CharField(write_only=True, required=True, min_length=8)
    work_schedules = WorkScheduleSerializer(many=True, required=False)

    class Meta:
        model  = User
        fields = [
            'first_name', 'last_name', 'username',
            'email', 'password', 'role',
            'location', 'phone',
            'work_schedules',
        ]

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, data):
        role           = data.get('role')
        work_schedules = data.get('work_schedules', [])

        # Schedule only required for floor staff roles
        if role in SCHEDULE_ROLES and not work_schedules:
            raise serializers.ValidationError({
                "work_schedules": f"Weekly schedule is required for role '{role}'."
            })

        # Location required for everyone except super_admin
        if role != 'super_admin' and not data.get('location'):
            raise serializers.ValidationError({
                "location": "Location assignment is required."
            })

        return data

    def create(self, validated_data):
        work_schedules_data = validated_data.pop('work_schedules', [])
        password            = validated_data.pop('password')

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        # Only create schedules for floor staff roles
        if user.role in SCHEDULE_ROLES:
            for schedule in work_schedules_data:
                UserWorkSchedule.objects.create(user=user, **schedule)

        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    """Update user — password optional, schedule optional"""
    password       = serializers.CharField(write_only=True, required=False, min_length=8)
    work_schedules = WorkScheduleSerializer(many=True, required=False)

    class Meta:
        model  = User
        fields = [
            'first_name', 'last_name', 'username',
            'email', 'password', 'role',
            'location', 'phone', 'is_active',
            'work_schedules',
        ]

    def update(self, instance, validated_data):
        work_schedules_data = validated_data.pop('work_schedules', None)
        password            = validated_data.pop('password', None)

        # Update user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        # Update work schedules if provided
        if work_schedules_data is not None:
            for schedule_data in work_schedules_data:
                day = schedule_data.get('day')
                UserWorkSchedule.objects.update_or_create(
                    user=instance,
                    day=day,
                    defaults={
                        'is_active':  schedule_data.get('is_active', False),
                        'start_time': schedule_data.get('start_time'),
                        'end_time':   schedule_data.get('end_time'),
                    }
                )

        # Refresh from DB to get updated schedules
        instance.refresh_from_db()
        return instance


# ================================================================
# USER STATS SERIALIZER
# ================================================================

class UserStatsSerializer(serializers.Serializer):
    district_managers = serializers.IntegerField()
    managers          = serializers.IntegerField()
    employees         = serializers.IntegerField()
 
 
# ── Minimal user info for task responses ──────────────────────────
class TaskUserSerializer(serializers.ModelSerializer):
    role_display  = serializers.CharField(source='get_role_display', read_only=True)
    location_name = serializers.CharField(source='location.name',    read_only=True)
 
    class Meta:
        model  = User
        fields = ['id', 'first_name', 'last_name', 'username', 'role', 'role_display', 'location_name']
 
 
# ================================================================
# TASK SERIALIZERS
# ================================================================
 
class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for task list table"""
    assigned_to_name  = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()
    location_name     = serializers.CharField(source='location.name', read_only=True)
    assigned_to_role  = serializers.CharField(source='assigned_to.get_role_display', read_only=True)
 
    class Meta:
        model  = Task
        fields = [
            'id', 'title', 'description',
            'location', 'location_name',
            'assigned_to', 'assigned_to_name', 'assigned_to_role',
            'due_date', 'status',
            'is_recurring', 'frequency',
            'requires_photo',
            'completed_by', 'completed_by_name',
            'created_at',
        ]
 
    def get_assigned_to_name(self, obj):
        return f"{obj.assigned_to.first_name} {obj.assigned_to.last_name}"
 
    def get_completed_by_name(self, obj):
        if obj.completed_by:
            return f"{obj.completed_by.first_name} {obj.completed_by.last_name}"
        return None
 
 
class TaskDetailSerializer(serializers.ModelSerializer):
    """Full task detail with all relations"""
    assigned_to  = TaskUserSerializer(read_only=True)
    completed_by = TaskUserSerializer(read_only=True)
    approved_by  = TaskUserSerializer(read_only=True)
    rejected_by  = TaskUserSerializer(read_only=True)
    created_by   = TaskUserSerializer(read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
 
    class Meta:
        model  = Task
        fields = [
            'id', 'title', 'description',
            'location', 'location_name',
            'assigned_to', 'created_by',
            'due_date', 'status',
            'is_recurring', 'frequency',
            'requires_photo', 'photo_url',
            'completed_by', 'completed_at',
            'approved_by',  'approved_at',
            'rejected_by',  'rejected_at', 'rejection_reason',
            'created_at',   'updated_at',
        ]
 
 
class TaskCreateSerializer(serializers.ModelSerializer):
    """Create task"""
 
    class Meta:
        model  = Task
        fields = [
            'title', 'description',
            'location', 'assigned_to',
            'due_date',
            'is_recurring', 'frequency',
            'requires_photo',
        ]
 
    def validate_assigned_to(self, value):
        if value.role not in ASSIGNABLE_ROLES:
            raise serializers.ValidationError(
                "Tasks can only be assigned to Tattoo Artists, Body Piercers, or Staff."
            )
        if not value.is_active:
            raise serializers.ValidationError("Cannot assign task to an inactive user.")
        return value
 
    def validate(self, data):
        # Assigned user must belong to the selected location
        assigned_to = data.get('assigned_to')
        location    = data.get('location')
 
        if assigned_to and location:
            if assigned_to.location != location:
                raise serializers.ValidationError({
                    "assigned_to": "This user does not belong to the selected location."
                })
 
        # If recurring, frequency must be set
        is_recurring = data.get('is_recurring', False)
        frequency    = data.get('frequency', 'none')
 
        if is_recurring and frequency == 'none':
            raise serializers.ValidationError({
                "frequency": "Please select a frequency for the recurring task (daily, weekly, or monthly)."
            })
 
        if not is_recurring:
            data['frequency'] = 'none'
 
        return data
 
 
class TaskUpdateSerializer(serializers.ModelSerializer):
    """Update task — all fields optional"""
 
    class Meta:
        model  = Task
        fields = [
            'title', 'description',
            'location', 'assigned_to',
            'due_date',
            'is_recurring', 'frequency',
            'requires_photo',
        ]
 
    def validate_assigned_to(self, value):
        if value.role not in ASSIGNABLE_ROLES:
            raise serializers.ValidationError(
                "Tasks can only be assigned to Tattoo Artists, Body Piercers, or Staff."
            )
        if not value.is_active:
            raise serializers.ValidationError("Cannot assign task to an inactive user.")
        return value
 
 
class TaskApproveSerializer(serializers.Serializer):
    """Approve a completed task"""
    pass  # No body needed — just the action
 
 
class TaskRejectSerializer(serializers.Serializer):
    """Reject a task with a reason"""
    rejection_reason = serializers.CharField(required=True, min_length=5)
 
 
class TaskStatsSerializer(serializers.Serializer):
    """Stats block at top of task list"""
    all_tasks = serializers.IntegerField()
    pending   = serializers.IntegerField()
    completed = serializers.IntegerField()
    approved  = serializers.IntegerField()
 
 
# ── Endpoint to get employees by location (for assign dropdown) ───
class LocationEmployeeSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
 
    class Meta:
        model  = User
        fields = ['id', 'first_name', 'last_name', 'username', 'role', 'role_display']
 

# ================================================================
# INSTRUCTION SERIALIZERS
# ================================================================
 
class InstructionSerializer(serializers.ModelSerializer):
    """Full instruction serializer — create / update / detail"""

    pdf_file = serializers.FileField(write_only=True, required=False)

    # ✅ FIX: override JSONField
    role_visibility = serializers.ListField(
        child=serializers.CharField(),
        required=True
    )

    class Meta:
        model  = Instruction
        fields = [
            'id', 'title', 'description',
            'pdf_url', 'pdf_filename',
            'role_visibility',
            'pdf_file',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'pdf_url', 'pdf_filename', 'created_at', 'updated_at']
    def validate_role_visibility(self, value):
        if not value:
            raise serializers.ValidationError("At least one role must be selected.")
        for role in value:
            if role not in VISIBILITY_ROLES:
                raise serializers.ValidationError(
                    f"'{role}' is not a valid role. Choose from: {VISIBILITY_ROLES}"
                )
        return value
 
    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Title cannot be blank.")
        return value.strip()
 
    def create(self, validated_data):
        pdf_file = validated_data.pop('pdf_file', None)
 
        instruction = Instruction(**validated_data)
 
        if pdf_file:
            import cloudinary.uploader
            upload_result        = cloudinary.uploader.upload(
                pdf_file,
                resource_type = 'raw',       # raw = non-image files like PDF
                folder        = 'instructions/',
                use_filename  = True,
                unique_filename = True,
            )
            instruction.pdf_url      = upload_result.get('secure_url')
            instruction.pdf_filename = pdf_file.name
 
        instruction.save()
        return instruction
 
    def update(self, instance, validated_data):
        pdf_file = validated_data.pop('pdf_file', None)
 
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
 
        if pdf_file:
            import cloudinary.uploader
            upload_result        = cloudinary.uploader.upload(
                pdf_file,
                resource_type   = 'raw',
                folder          = 'instructions/',
                use_filename    = True,
                unique_filename = True,
            )
            instance.pdf_url      = upload_result.get('secure_url')
            instance.pdf_filename = pdf_file.name
 
        instance.save()
        return instance
 
 
class InstructionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list"""
    class Meta:
        model  = Instruction
        fields = [
            'id', 'title', 'description',
            'pdf_url', 'pdf_filename',
            'role_visibility',
            'created_at',
        ]
 
 
class InstructionStatsSerializer(serializers.Serializer):
    """Stats block at top of instruction page"""
    total_instructions = serializers.IntegerField()
    tattoo_artists     = serializers.IntegerField()
    body_piercers      = serializers.IntegerField()
    staff              = serializers.IntegerField()
 