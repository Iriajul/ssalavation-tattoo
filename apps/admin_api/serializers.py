# apps/admin_api/serializers.py
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from .models import FAQ, Attendance, Location, QRSession, SplashScreen, UserWorkSchedule, Task, Instruction, Notification

User = get_user_model()

# Roles that require a weekly schedule
SCHEDULE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']
ASSIGNABLE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']

# ================================================================
# AUTH SERIALIZERS
# ================================================================

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user

        # ← add clock_in_user
        if user.role not in ['super_admin', 'district_manager', 'branch_manager', 'clock_in_user']:
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
        is_active  = data.get('is_active', self.instance.is_active if self.instance else False)
        start_time = data.get('start_time', self.instance.start_time if self.instance else None)
        end_time   = data.get('end_time',   self.instance.end_time   if self.instance else None)

        if is_active:
            if not start_time:
                raise serializers.ValidationError({"start_time": "Start time is required when day is active."})
            if not end_time:
                raise serializers.ValidationError({"end_time": "End time is required when day is active."})
            if start_time >= end_time:
                raise serializers.ValidationError({"end_time": "End time must be after start time."})
        return data


# ================================================================
# USER SERIALIZERS
# ================================================================

class UserListSerializer(serializers.ModelSerializer):
    role_display  = serializers.CharField(source='get_role_display', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
    joined        = serializers.DateTimeField(source='date_joined', format='%b %d, %Y', read_only=True)
    user_status   = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            'id', 'first_name', 'last_name', 'username',
            'email', 'role', 'role_display',
            'location', 'location_name',
            'is_active', 'is_suspended', 'user_status', 'joined',
        ]

    def get_user_status(self, obj):
        if obj.is_suspended:
            return 'suspended'
        if not obj.is_active:
            return 'inactive'
        return 'active'


class UserDetailSerializer(serializers.ModelSerializer):
    role_display   = serializers.CharField(source='get_role_display', read_only=True)
    location_name  = serializers.CharField(source='location.name', read_only=True)
    work_schedules = WorkScheduleSerializer(many=True, read_only=True)
    user_status    = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            'id', 'first_name', 'last_name', 'username',
            'email', 'role', 'role_display', 'phone',
            'location', 'location_name',
            'is_active', 'is_suspended', 'user_status', 'date_joined',
            'work_schedules',
        ]

    def get_user_status(self, obj):
        if obj.is_suspended:
            return 'suspended'
        if not obj.is_active:
            return 'inactive'
        return 'active'


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
        roles_without_location = ['super_admin', 'district_manager']
        if role not in roles_without_location and not data.get('location'):
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
    password       = serializers.CharField(write_only=True, required=False, min_length=8)
    work_schedules = WorkScheduleSerializer(many=True, required=False)
    status         = serializers.ChoiceField(
        choices=['active', 'suspended'],
        required=False
    )

    class Meta:
        model  = User
        fields = [
            'first_name', 'last_name', 'username',
            'email', 'password', 'role',
            'location', 'phone',
            'status',
            'work_schedules',
        ]

    def validate(self, data):
        # Get role — use incoming role or existing instance role
        role           = data.get('role', self.instance.role if self.instance else None)
        work_schedules = data.get('work_schedules', None)

        # Block schedule update for manager roles
        MANAGER_ROLES = ['district_manager', 'branch_manager', 'super_admin']
        if work_schedules is not None and role in MANAGER_ROLES:
            raise serializers.ValidationError({
                "work_schedules": f"Work schedule cannot be set for role '{role}'."
            })

        return data

    def update(self, instance, validated_data):
        work_schedules_data = validated_data.pop('work_schedules', None)
        password            = validated_data.pop('password', None)
        status              = validated_data.pop('status', None)

        # ── Handle status change ──────────────────────────────────
        if status == 'suspended':
            instance.is_suspended = True
            instance.is_active    = False
        elif status == 'active':
            instance.is_suspended = False
            instance.is_active    = True

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        # ── Schedule update ───────────────────────────────────────
        SCHEDULE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']

        if work_schedules_data is not None:
            if instance.role in SCHEDULE_ROLES:
                for schedule_data in work_schedules_data:
                    day       = schedule_data.get('day')
                    is_active = schedule_data.get('is_active', False)

                    # Clear times when day is toggled off
                    start_time = schedule_data.get('start_time') if is_active else None
                    end_time   = schedule_data.get('end_time')   if is_active else None

                    UserWorkSchedule.objects.update_or_create(
                        user=instance,
                        day=day,
                        defaults={
                            'is_active':  is_active,
                            'start_time': start_time,
                            'end_time':   end_time,
                        }
                    )
            # If role changed to manager type — delete all schedules
            else:
                UserWorkSchedule.objects.filter(user=instance).delete()

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
        fields = ['id', 'first_name', 'last_name', 'username', 'email', 'role', 'role_display', 'location_name']
 
 

# ================================================================
# TASK SERIALIZERS — UPDATED
# ================================================================
 
class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for task list table"""
    assigned_to_name     = serializers.SerializerMethodField()
    assigned_to_email = serializers.CharField(source='assigned_to.email', read_only=True)
    assigned_to_role     = serializers.CharField(source='assigned_to.get_role_display', read_only=True)
    completed_by_name    = serializers.SerializerMethodField()
    completed_by_role    = serializers.SerializerMethodField()
    location_name        = serializers.CharField(source='location.name', read_only=True)
    can_fire = serializers.SerializerMethodField()
 
    class Meta:
        model  = Task
        fields = [
            'id', 'title', 'description',
            'location', 'location_name',
            'assigned_to', 'assigned_to_name', 'assigned_to_email','assigned_to_role',
            'due_date', 'status',
            'is_recurring', 'frequency',
            'requires_photo',
            'completed_by', 'completed_by_name', 'completed_by_role',
            'is_fired',
            'can_fire',
            'created_at',
        ]
 
    def get_assigned_to_name(self, obj):
        return f"{obj.assigned_to.first_name} {obj.assigned_to.last_name}".strip()
    
    def get_can_fire(self, obj):
        # Show fire button only if task is overdue and user not already fired
        return obj.status == 'overdue' and not obj.is_fired
 
    def get_completed_by_name(self, obj):
        if obj.completed_by:
            return f"{obj.completed_by.first_name} {obj.completed_by.last_name}".strip()
        return None
 
    def get_completed_by_role(self, obj):
        if obj.completed_by:
            return obj.completed_by.get_role_display()
        return None
 
 
class TaskDetailSerializer(serializers.ModelSerializer):
    """Full task detail with all relations"""
    assigned_to   = TaskUserSerializer(read_only=True)
    completed_by  = TaskUserSerializer(read_only=True)
    approved_by   = TaskUserSerializer(read_only=True)
    rejected_by   = TaskUserSerializer(read_only=True)
    created_by    = TaskUserSerializer(read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
    can_fire = serializers.SerializerMethodField()
 
    # ── Human readable status label ───────────────────────────
    status_display = serializers.SerializerMethodField()
 
    class Meta:
        model  = Task
        fields = [
            'id', 'title', 'description',
            'location', 'location_name',
            'assigned_to', 'created_by',
            'due_date', 'status', 'status_display',
            'is_recurring', 'frequency',
            'requires_photo', 'photo_url',
            'completed_by', 'completed_at',
            'approved_by',  'approved_at',
            'rejected_by',  'rejected_at', 'rejection_reason',
            'is_fired',
            'can_fire',
            'created_at',   'updated_at',
        ]

    def get_can_fire(self, obj): 
        return obj.status == 'overdue' and not obj.is_fired   
 
    def get_status_display(self, obj):
        status_labels = {
            'pending':        'Pending',
            'completed':      'Completed',
            'awaiting_review': 'Awaiting Review',
            'approved':       'Approved',
            'rejected':       'Rejected',
            'overdue':        'Overdue',
        }
        return status_labels.get(obj.status, obj.status)
 
 
class TaskCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Task
        fields = [
            'title', 'description',
            'location', 'assigned_to',
            'due_date',
            'is_recurring', 'frequency',
            'requires_photo',
        ]

    def validate_due_date(self, value):
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError(
                f"Due date cannot be in the past. Today is {today}."
            )
        return value    
 
    def validate_assigned_to(self, value):
        if value.role not in ASSIGNABLE_ROLES:
            raise serializers.ValidationError(
                "Tasks can only be assigned to Tattoo Artists, Body Piercers, or Staff."
            )
        if not value.is_active:
            raise serializers.ValidationError("Cannot assign task to an inactive user.")
        return value
 
    def validate(self, data):
        assigned_to = data.get('assigned_to')
        location    = data.get('location')
 
        if assigned_to and location:
            if assigned_to.location != location:
                raise serializers.ValidationError({
                    "assigned_to": "This user does not belong to the selected location."
                })
 
        is_recurring = data.get('is_recurring', False)
        frequency    = data.get('frequency', 'none')
 
        if is_recurring and frequency == 'none':
            raise serializers.ValidationError({
                "frequency": "Please select a frequency for the recurring task."
            })
 
        if not is_recurring:
            data['frequency'] = 'none'
 
        return data
 
 
class TaskUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Task
        fields = [
            'title', 'description',
            'location', 'assigned_to',
            'due_date',
            'is_recurring', 'frequency',
            'requires_photo',
        ]

    def validate_due_date(self, value):
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError(
                f"Due date cannot be in the past. Today is {today}."
            )
        return value

    def validate_assigned_to(self, value):
        if value.role not in ASSIGNABLE_ROLES:
            raise serializers.ValidationError(
                "Tasks can only be assigned to Tattoo Artists, Body Piercers, or Staff."
            )
        if not value.is_active:
            raise serializers.ValidationError("Cannot assign task to an inactive user.")
        return value

    def validate(self, data):
        assigned_to = data.get('assigned_to', getattr(self.instance, 'assigned_to', None))
        location    = data.get('location',    getattr(self.instance, 'location', None))

        if assigned_to and location:
            if assigned_to.location != location:
                raise serializers.ValidationError({
                    "assigned_to": "This user does not belong to the selected location."
                })

        is_recurring = data.get('is_recurring', getattr(self.instance, 'is_recurring', False))
        frequency    = data.get('frequency',    getattr(self.instance, 'frequency', 'none'))

        if is_recurring and frequency == 'none':
            raise serializers.ValidationError({
                "frequency": "Please select a frequency for the recurring task."
            })
        if not is_recurring:
            data['frequency'] = 'none'

        return data
 
class TaskApproveSerializer(serializers.Serializer):
    pass
 
 
class TaskRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(required=True, min_length=5)
 
 
class TaskStatsSerializer(serializers.Serializer):
    """Updated stats — all_tasks, overdue, completed, rejected"""
    all_tasks = serializers.IntegerField()
    overdue   = serializers.IntegerField()
    completed = serializers.IntegerField()
    rejected  = serializers.IntegerField()
 
 
class LocationEmployeeSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
 
    class Meta:
        model  = User
        fields = ['id', 'first_name', 'last_name', 'username',  'email','role', 'role_display']
 
 
# ── Fire User Serializer ──────────────────────────────────────────
class FireUserSerializer(serializers.Serializer):
    fire_reason = serializers.CharField(required=True, min_length=5)


# ================================================================
# INSTRUCTION SERIALIZERS
# ================================================================
 
VISIBILITY_ROLES = [
    'tattoo_artist',
    'body_piercer',
    'staff',
    'branch_manager',
    'district_manager',
]
 
 
class InstructionSerializer(serializers.ModelSerializer):
    """Full instruction serializer — create / update / detail"""
    pdf_file        = serializers.FileField(write_only=True, required=False)
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
        pdf_file    = validated_data.pop('pdf_file', None)
        instruction = Instruction(**validated_data)
 
        if pdf_file:
            import cloudinary.uploader
            upload_result        = cloudinary.uploader.upload(
                pdf_file,
                resource_type   = 'raw',
                folder          = 'instructions/',
                use_filename    = True,
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
    branch_managers    = serializers.IntegerField()
    district_managers  = serializers.IntegerField()
 

class SplashScreenSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SplashScreen
        fields = ['id', 'web_image_url', 'app_image_url', 'updated_at']


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FAQ
        fields = ['id', 'question', 'answer', 'created_at']


class AdminProfileSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    member_since = serializers.DateTimeField(source='date_joined', format='%B %d, %Y', read_only=True)
    full_name     = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            'id', 'first_name','last_name', 'email', 'full_name',
            'role', 'role_display', 'is_active',
            'profile_photo', 'member_since', 'last_login_at',
        ]
        
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

class AdminChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password     = serializers.CharField(min_length=8, required=True)
    confirm_password = serializers.CharField(min_length=8, required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data



class QRSessionSerializer(serializers.ModelSerializer):
    present_count    = serializers.IntegerField(read_only=True)
    location_name  = serializers.CharField(source='location.name', read_only=True)
    late_count       = serializers.IntegerField(read_only=True)
    absent_count     = serializers.IntegerField(read_only=True)
    is_expired       = serializers.BooleanField(read_only=True)
    interval_display = serializers.CharField(
        source='get_refresh_interval_display', read_only=True
    )

    class Meta:
        model  = QRSession
        fields = [
            'id', 'token', 'location', 'location_name', 'refresh_interval',
            'interval_display', 'expires_at', 'is_active',
            'is_expired', 'present_count', 'late_count',
            'absent_count', 'created_at',
        ]


class QRSessionListSerializer(serializers.ModelSerializer):
    """Lightweight for QR history list"""
    present_count    = serializers.IntegerField(read_only=True)
    late_count       = serializers.IntegerField(read_only=True)
    absent_count     = serializers.IntegerField(read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
    location_id   = serializers.IntegerField(source='location.id', read_only=True)
    interval_display = serializers.CharField(
        source='get_refresh_interval_display', read_only=True
    )

    class Meta:
        model  = QRSession
        fields = [
            'id', 'token', 'refresh_interval', 'interval_display',
            'location_id',
            'location_name',
            'expires_at', 'is_active', 'present_count',
            'late_count', 'absent_count', 'created_at',
        ]


class AttendanceSerializer(serializers.ModelSerializer):
    employee_name  = serializers.SerializerMethodField()
    employee_email = serializers.CharField(source='user.email', read_only=True)
    employee_role  = serializers.CharField(
        source='user.get_role_display', read_only=True
    )
    location_name  = serializers.CharField(source='location.name', read_only=True)

    class Meta:
        model  = Attendance
        fields = [
            'id', 'employee_name', 'employee_email', 'employee_role',
            'location_name', 'date', 'status',
            'clock_in', 'clock_out', 'created_at',
        ]

    def get_employee_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()
    


class BranchManagerDashboardSerializer(serializers.Serializer):
    """Branch manager dashboard response"""
 
    # Greeting
    greeting      = serializers.CharField()
    date_display  = serializers.CharField()
    location_name = serializers.CharField()
 
    # Stats
    total_employees       = serializers.IntegerField()
    pending_verifications = serializers.IntegerField()
 
    # Attendance
    today_attendance = serializers.DictField()
 
    # Today's staff
    today_staff = serializers.ListField()
 
    # Recent task activity
    recent_tasks = serializers.ListField()
 
    

class BranchManagerTaskCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Task
        fields = [
            'title', 'description',
            'assigned_to', 'due_date',
            'is_recurring', 'frequency',
            'requires_photo',
        ]
        # No location field — set automatically from manager's location

    def validate_assigned_to(self, value):
        if value.role not in ASSIGNABLE_ROLES:
            raise serializers.ValidationError(
                "Tasks can only be assigned to Tattoo Artists, Body Piercers, or Staff."
            )
        if not value.is_active:
            raise serializers.ValidationError(
                "Cannot assign task to an inactive user."
            )
        return value

    def validate(self, data):
        is_recurring = data.get('is_recurring', False)
        frequency    = data.get('frequency', 'none')

        if is_recurring and frequency == 'none':
            raise serializers.ValidationError({
                "frequency": "Please select a frequency for the recurring task."
            })
        if not is_recurring:
            data['frequency'] = 'none'

        return data
    
class BranchManagerTaskListSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.SerializerMethodField()
    assigned_to_role = serializers.CharField(
        source='assigned_to.get_role_display', read_only=True
    )
    submitted_at     = serializers.DateTimeField(
        source='created_at', format='%m/%d/%Y', read_only=True
    )
    can_edit         = serializers.SerializerMethodField()

    class Meta:
        model  = Task
        fields = [
            'id', 'title', 'description',
            'assigned_to', 'assigned_to_name', 'assigned_to_role',
            'due_date', 'status', 'submitted_at',
            'is_recurring', 'frequency',
            'requires_photo',
            'can_edit',
        ]

    def get_assigned_to_name(self, obj):
        return f"{obj.assigned_to.first_name} {obj.assigned_to.last_name}".strip()

    def get_can_edit(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.status == 'pending' and obj.created_by_id == request.user.id
        return False

class NotificationStatsSerializer(serializers.Serializer):
    total_sent       = serializers.IntegerField()
    delivered        = serializers.IntegerField()
    active_locations = serializers.IntegerField()

class NotificationCreateSerializer(serializers.Serializer):
    email    = serializers.EmailField(required=False)   # optional — if empty, send to all
    location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(),
        required=False                                  # optional — if empty, all locations
    )
    message  = serializers.CharField(required=True, min_length=5)

    def validate(self, data):
        email    = data.get('email')
        location = data.get('location')

        # If email provided, location must also be provided
        if email and not location:
            raise serializers.ValidationError({
                "location": "Location is required when sending to a specific user."
            })

        return data

class NotificationSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source='location.name', read_only=True)
    sent_by_name  = serializers.SerializerMethodField()

    class Meta:
        model  = Notification
        fields = [
            'id', 'email',
            'location', 'location_name',
            'message', 'status',
            'sent_by', 'sent_by_name',
            'created_at',
        ]
        read_only_fields = ['id', 'status', 'sent_by', 'created_at']

    def get_sent_by_name(self, obj):
        if obj.sent_by:
            return f"{obj.sent_by.first_name} {obj.sent_by.last_name}".strip() or obj.sent_by.username
        return None

