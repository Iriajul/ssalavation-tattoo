# apps/admin_api/serializers.py
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from .models import FAQ, Attendance, Location, QRSession, SplashScreen, UserWorkSchedule, Task, TaskAssignment, Instruction, AdminNotification, RecurringTaskTemplate
from .recurrence import build_rrule, generate_instances, rrule_to_recurrence, VALID_WEEKDAYS

User = get_user_model()

# Roles that require a weekly schedule
SCHEDULE_ROLES = ['tattoo_artist', 'body_piercer', 'staff', 'branch_manager', 'district_manager']
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
    joined        = serializers.DateTimeField(source='date_joined', format='%Y-%m-%d', read_only=True)
    user_status   = serializers.SerializerMethodField()
    work_schedules = WorkScheduleSerializer(many=True, read_only=True)

    class Meta:
        model  = User
        fields = [
            'id', 'first_name', 'last_name', 'username',
            'email', 'role', 'role_display',
            'location', 'location_name',
            'is_active', 'is_suspended', 'user_status', 'joined', 'work_schedules',
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
        MANAGER_ROLES = ['super_admin']
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
        SCHEDULE_ROLES = ['tattoo_artist', 'body_piercer', 'staff', 'branch_manager', 'district_manager']

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
# TASK ASSIGNMENT SERIALIZER
# ================================================================

class TaskAssignmentSerializer(serializers.ModelSerializer):
    assignment_id  = serializers.IntegerField(source='id', read_only=True)
    task_id        = serializers.IntegerField(read_only=True)
    employee       = serializers.SerializerMethodField()
    approved_by    = TaskUserSerializer(read_only=True)
    rejected_by    = TaskUserSerializer(read_only=True)
    status_display = serializers.SerializerMethodField()
    can_fire       = serializers.SerializerMethodField()

    class Meta:
        model  = TaskAssignment
        fields = [
            'assignment_id', 'task_id',
            'employee', 'status', 'status_display',
            'is_fired', 'can_fire', 'photo_url',
            'completed_at', 'approved_by', 'approved_at',
            'rejected_by',  'rejected_at', 'rejection_reason',
            'created_at',
        ]

    def get_employee(self, obj):
        u = obj.employee
        return {
            'employee_id':  u.id,
            'name':         f"{u.first_name} {u.last_name}".strip() or u.username,
            'email':        u.email,
            'role':         u.role,
            'role_display': u.get_role_display(),
        }

    def get_status_display(self, obj):
        labels = {
            'pending': 'Pending', 'awaiting_review': 'Awaiting Review',
            'approved': 'Approved', 'rejected': 'Rejected', 'overdue': 'Overdue',
        }
        return labels.get(obj.status, obj.status)

    def get_can_fire(self, obj):
        return obj.status == 'overdue' and not obj.is_fired


# ================================================================
# TASK SERIALIZERS
# ================================================================

def _task_recurrence(obj):
    """The recurrence object for a task, read from its template (None for one-time tasks)."""
    if obj.template_id and obj.template:
        return rrule_to_recurrence(obj.template.rrule)
    return None


def _series_status_counts(obj, context):
    """
    status_counts for a collapsed list row.

    - Recurring task: the series-level aggregate from `series_meta` (counts only
      occurrences that have come due). If nothing is due yet → all zeros (NOT the
      representative's future assignments).
    - One-time task: count its own assignments.
    """
    zeros = {'pending': 0, 'awaiting_review': 0, 'approved': 0, 'rejected': 0, 'overdue': 0}
    if obj.template_id:
        meta = (context.get('series_meta') or {}).get(obj.template_id)
        if meta is not None and 'status_counts' in meta:
            return meta['status_counts']
        return dict(zeros)
    counts = dict(zeros)
    for a in obj.assignments.all():
        if a.status in counts:
            counts[a.status] += 1
    return counts


class TaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for task list — task + assignment summary (collapsed)."""
    task_id           = serializers.IntegerField(source='id', read_only=True)
    template_id       = serializers.SerializerMethodField()
    assignments       = serializers.SerializerMethodField()
    status_counts     = serializers.SerializerMethodField()
    location_name     = serializers.CharField(source='location.name', read_only=True)
    created_by        = TaskUserSerializer(read_only=True)
    recurrence        = serializers.SerializerMethodField()
    next_due_date     = serializers.SerializerMethodField()
    total_occurrences = serializers.SerializerMethodField()

    class Meta:
        model  = Task
        fields = [
            'task_id', 'template_id', 'title', 'description',
            'location', 'location_name',
            'due_date', 'next_due_date', 'is_recurring', 'frequency', 'recurrence',
            'total_occurrences', 'requires_photo',
            'created_by', 'created_at',
            'assignments', 'status_counts',
        ]

    def get_template_id(self, obj):
        return obj.template_id

    def get_recurrence(self, obj):
        return _task_recurrence(obj)

    def get_next_due_date(self, obj):
        # The collapsed row's representative IS the next occurrence, so due_date is it.
        return obj.due_date if obj.template_id else None

    def get_total_occurrences(self, obj):
        if obj.template_id:
            meta = (self.context.get('series_meta') or {}).get(obj.template_id)
            if meta:
                return meta.get('total_occurrences', 1)
        return 1

    def get_assignments(self, obj):
        # Full assignment shape (same as the task-detail endpoint).
        return TaskAssignmentSerializer(obj.assignments.all(), many=True).data

    def get_status_counts(self, obj):
        return _series_status_counts(obj, self.context)


class TaskDetailSerializer(serializers.ModelSerializer):
    """Full task detail with all assignments"""
    task_id       = serializers.IntegerField(source='id', read_only=True)
    assignments   = TaskAssignmentSerializer(many=True, read_only=True)
    status_counts = serializers.SerializerMethodField()
    created_by    = TaskUserSerializer(read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
    recurrence    = serializers.SerializerMethodField()

    class Meta:
        model  = Task
        fields = [
            'task_id', 'title', 'description',
            'location', 'location_name',
            'due_date', 'is_recurring', 'frequency', 'recurrence', 'requires_photo',
            'created_by', 'created_at', 'updated_at',
            'assignments', 'status_counts',
        ]

    def get_recurrence(self, obj):
        return _task_recurrence(obj)

    def get_status_counts(self, obj):
        counts = {'pending': 0, 'awaiting_review': 0, 'approved': 0, 'rejected': 0, 'overdue': 0}
        for a in obj.assignments.all():
            if a.status in counts:
                counts[a.status] += 1
        return counts


class RecurrenceSerializer(serializers.Serializer):
    """The recurrence pattern for a recurring task (no dates — start_date lives on the task)."""
    frequency    = serializers.ChoiceField(choices=['daily', 'weekly', 'monthly', 'yearly'])
    interval     = serializers.IntegerField(min_value=1, default=1)
    weekdays     = serializers.ListField(
        child=serializers.ChoiceField(choices=VALID_WEEKDAYS),
        required=False, allow_null=True, allow_empty=True,
    )
    day_of_month = serializers.IntegerField(min_value=1, max_value=31, required=False, allow_null=True)

    def validate(self, data):
        freq     = data['frequency']
        weekdays = data.get('weekdays')
        dom      = data.get('day_of_month')

        if freq == 'weekly':
            if not weekdays:
                raise serializers.ValidationError({'weekdays': 'weekdays is required for a weekly recurrence.'})
        elif weekdays:
            raise serializers.ValidationError({'weekdays': f'weekdays is only allowed for a weekly recurrence, not {freq}.'})

        if freq == 'monthly':
            if not dom:
                raise serializers.ValidationError({'day_of_month': 'day_of_month is required for a monthly recurrence.'})
        elif dom:
            raise serializers.ValidationError({'day_of_month': f'day_of_month is only allowed for a monthly recurrence, not {freq}.'})

        return data


class RecurringTaskMixin:
    """
    Shared cross-field validation + create logic for the task-create serializers.

    One-time  → requires due_date; rejects start_date + recurrence.
    Recurring → requires start_date + recurrence; rejects due_date. Builds a
                RecurringTaskTemplate and materializes its instances; returns the
                first generated Task so the calling view's response/notification
                flow is identical to a one-time task.
    """

    def _validate_recurrence_fields(self, data):
        is_recurring = data.get('is_recurring', False)
        today        = timezone.localdate()

        if is_recurring:
            if not data.get('start_date'):
                raise serializers.ValidationError({'start_date': 'start_date is required for a recurring task.'})
            if not data.get('recurrence'):
                raise serializers.ValidationError({'recurrence': 'recurrence is required for a recurring task.'})
            if data.get('due_date'):
                raise serializers.ValidationError({'due_date': 'Do not send due_date for a recurring task; use start_date.'})
            if data['start_date'] < today:
                raise serializers.ValidationError({'start_date': f"start_date cannot be in the past. Today is {today}."})
        else:
            if not data.get('due_date'):
                raise serializers.ValidationError({'due_date': 'due_date is required for a one-time task.'})
            if data.get('start_date'):
                raise serializers.ValidationError({'start_date': 'Do not send start_date for a one-time task.'})
            if data.get('recurrence'):
                raise serializers.ValidationError({'recurrence': 'Do not send recurrence for a one-time task.'})
            data['frequency'] = 'none'

    def _build_task(self, validated_data, employees, location, created_by):
        """Create either a one-time Task or a recurring template; return a representative Task."""
        is_recurring = validated_data.get('is_recurring', False)
        recurrence   = validated_data.get('recurrence')
        start_date   = validated_data.get('start_date')

        if not is_recurring:
            task = Task.objects.create(
                title          = validated_data['title'],
                description    = validated_data.get('description'),
                location       = location,
                created_by     = created_by,
                due_date       = validated_data['due_date'],
                is_recurring   = False,
                frequency      = 'none',
                requires_photo = validated_data.get('requires_photo', False),
            )
            for emp in employees:
                TaskAssignment.objects.create(task=task, employee=emp)
            return task

        template = RecurringTaskTemplate.objects.create(
            title          = validated_data['title'],
            description    = validated_data.get('description'),
            location       = location,
            created_by     = created_by,
            start_date     = start_date,
            rrule          = build_rrule(recurrence),
            requires_photo = validated_data.get('requires_photo', False),
        )
        template.assignees.set(employees)
        created = generate_instances(template)
        return created[0] if created else None


class TaskCreateSerializer(RecurringTaskMixin, serializers.Serializer):
    """Validates task + employee list for create (one-time or recurring)."""
    title          = serializers.CharField(max_length=255)
    description    = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    location       = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    assigned_to    = serializers.ListField(
        child=serializers.IntegerField(), min_length=1,
        help_text='List of employee IDs'
    )
    due_date       = serializers.DateField(required=False)
    start_date     = serializers.DateField(required=False)
    is_recurring   = serializers.BooleanField(default=False)
    recurrence     = RecurrenceSerializer(required=False)
    requires_photo = serializers.BooleanField(default=False)

    def validate_due_date(self, value):
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError(f"Due date cannot be in the past. Today is {today}.")
        return value

    def validate(self, data):
        emp_ids  = data.get('assigned_to', [])
        location = data.get('location')
        employees = User.objects.filter(id__in=emp_ids, is_active=True)
        found_ids = set(employees.values_list('id', flat=True))

        errors = []
        for eid in emp_ids:
            if eid not in found_ids:
                errors.append(f"Employee {eid} not found or inactive.")
        if errors:
            raise serializers.ValidationError({'assigned_to': errors})

        for emp in employees:
            if emp.role not in ASSIGNABLE_ROLES:
                errors.append(f"{emp.get_full_name()} is not a Tattoo Artist, Body Piercer, or Staff.")
            elif location and emp.location != location:
                errors.append(f"{emp.get_full_name()} does not belong to the selected location.")
        if errors:
            raise serializers.ValidationError({'assigned_to': errors})

        self._validate_recurrence_fields(data)

        data['_employees'] = list(employees)
        return data

    def create(self, validated_data):
        employees  = validated_data.pop('_employees')
        validated_data.pop('assigned_to', None)
        created_by = validated_data.get('created_by')
        location   = validated_data['location']
        return self._build_task(validated_data, employees, location, created_by)


class TaskUpdateSerializer(serializers.Serializer):
    """Updates task fields; optionally moves location / changes assignees / recurrence."""
    title          = serializers.CharField(max_length=255, required=False)
    description    = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    location       = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), required=False)
    due_date       = serializers.DateField(required=False)
    start_date     = serializers.DateField(required=False)
    recurrence     = RecurrenceSerializer(required=False)
    requires_photo = serializers.BooleanField(required=False)
    assigned_to    = serializers.ListField(
        child=serializers.IntegerField(), required=False,
        help_text='The full set of assignee IDs (replaces the current assignees).'
    )

    def validate_due_date(self, value):
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError(f"Due date cannot be in the past. Today is {today}.")
        return value

    def validate_start_date(self, value):
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError(f"start_date cannot be in the past. Today is {today}.")
        return value

    def validate(self, data):
        task                 = self.context.get('task')
        allowed_location_ids = self.context.get('allowed_location_ids')
        new_location         = data.get('location')

        # The location used to validate assignees: the new one if the task is being
        # moved, otherwise the task's current location.
        effective_location = new_location or (task.location if task else None)

        # District managers may only move a task to one of their locations.
        if new_location and allowed_location_ids is not None and new_location.id not in allowed_location_ids:
            raise serializers.ValidationError({'location': 'You can only move a task to one of your locations.'})

        # Moving to a different location requires providing the new assignees.
        moving = bool(new_location and task and new_location.id != task.location_id)
        if moving and not data.get('assigned_to'):
            raise serializers.ValidationError(
                {'assigned_to': 'When changing location, provide assigned_to with employees of the new location.'}
            )

        emp_ids = data.get('assigned_to', [])
        if emp_ids:
            employees = User.objects.filter(id__in=emp_ids, is_active=True)
            found_ids = set(employees.values_list('id', flat=True))
            errors = []
            for eid in emp_ids:
                if eid not in found_ids:
                    errors.append(f"Employee {eid} not found or inactive.")
            for emp in employees:
                if emp.role not in ASSIGNABLE_ROLES:
                    errors.append(f"{emp.get_full_name()} is not a Tattoo Artist, Body Piercer, or Staff.")
                # District (allowed_location_ids) without a location change: employees
                # may come from any of the district's locations. Otherwise they must
                # match the effective (new or current) location.
                elif allowed_location_ids is not None and not moving:
                    if emp.location_id not in allowed_location_ids:
                        errors.append(f"{emp.get_full_name()} does not belong to any of your locations.")
                elif effective_location and emp.location_id != effective_location.id:
                    errors.append(f"{emp.get_full_name()} does not belong to the selected location.")
            if errors:
                raise serializers.ValidationError({'assigned_to': errors})
            data['_employees'] = list(employees)

        # recurrence/start_date may only be edited on a recurring task; due_date
        # only makes sense for a one-time task.
        task = self.context.get('task')
        if task is not None:
            if (data.get('recurrence') or data.get('start_date')) and not task.template_id:
                raise serializers.ValidationError(
                    {'recurrence': 'This is a one-time task; recurrence/start_date cannot be set.'}
                )
            if data.get('due_date') and task.template_id:
                raise serializers.ValidationError(
                    {'due_date': 'This is a recurring task; change start_date/recurrence instead of due_date.'}
                )
        return data


class TaskRejectSerializer(serializers.Serializer):
    assignment_id    = serializers.IntegerField(required=True)
    rejection_reason = serializers.CharField(required=True, min_length=5)


class TaskApproveSerializer(serializers.Serializer):
    assignment_id = serializers.IntegerField(required=True)


class TaskStatsSerializer(serializers.Serializer):
    all_tasks = serializers.IntegerField()
    overdue   = serializers.IntegerField()
    completed = serializers.IntegerField()
    rejected  = serializers.IntegerField()


class LocationEmployeeSerializer(serializers.ModelSerializer):
    name           = serializers.SerializerMethodField()
    role_display   = serializers.CharField(source='get_role_display', read_only=True)
    work_schedules = WorkScheduleSerializer(many=True, read_only=True)

    class Meta:
        model  = User
        fields = ['id', 'name', 'email', 'role', 'role_display', 'work_schedules']

    def get_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or obj.username


class FireUserSerializer(serializers.Serializer):
    assignment_id = serializers.IntegerField(required=True)
    fire_reason   = serializers.CharField(required=True, min_length=5)


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
    duration_minutes      = serializers.IntegerField(read_only=True)
    duration_seconds_part = serializers.IntegerField(read_only=True)
    duration_display      = serializers.CharField(read_only=True)

    class Meta:
        model  = QRSession
        fields = [
            'id', 'token', 'location', 'location_name',
            'duration_seconds', 'duration_minutes', 'duration_seconds_part',
            'duration_display', 'expires_at', 'is_active',
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
    duration_minutes      = serializers.IntegerField(read_only=True)
    duration_seconds_part = serializers.IntegerField(read_only=True)
    duration_display      = serializers.CharField(read_only=True)

    class Meta:
        model  = QRSession
        fields = [
            'id', 'token',
            'duration_seconds', 'duration_minutes', 'duration_seconds_part',
            'duration_display',
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
 
    

class BranchManagerTaskCreateSerializer(RecurringTaskMixin, serializers.Serializer):
    """Branch manager creates a task (one-time or recurring) for employees at their location."""
    title          = serializers.CharField(max_length=255)
    description    = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    assigned_to    = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    due_date       = serializers.DateField(required=False)
    start_date     = serializers.DateField(required=False)
    is_recurring   = serializers.BooleanField(default=False)
    recurrence     = RecurrenceSerializer(required=False)
    requires_photo = serializers.BooleanField(default=False)

    def validate_due_date(self, value):
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError(f"Due date cannot be in the past. Today is {today}.")
        return value

    def validate(self, data):
        location = self.context.get('location')
        emp_ids  = data.get('assigned_to', [])
        employees = User.objects.filter(id__in=emp_ids, is_active=True)
        found_ids = set(employees.values_list('id', flat=True))
        errors = []
        for eid in emp_ids:
            if eid not in found_ids:
                errors.append(f"Employee {eid} not found or inactive.")
        for emp in employees:
            if emp.role not in ASSIGNABLE_ROLES:
                errors.append(f"{emp.get_full_name()} is not a Tattoo Artist, Body Piercer, or Staff.")
            elif location and emp.location != location:
                errors.append(f"{emp.get_full_name()} does not belong to your location.")
        if errors:
            raise serializers.ValidationError({'assigned_to': errors})

        self._validate_recurrence_fields(data)

        data['_employees'] = list(employees)
        return data

    def create(self, validated_data):
        employees  = validated_data.pop('_employees')
        validated_data.pop('assigned_to', None)
        created_by = validated_data.get('created_by')
        location   = self.context.get('location')
        return self._build_task(validated_data, employees, location, created_by)


class BranchManagerTaskListSerializer(serializers.ModelSerializer):
    task_id           = serializers.IntegerField(source='id', read_only=True)
    template_id       = serializers.SerializerMethodField()
    assignments       = serializers.SerializerMethodField()
    status_counts     = serializers.SerializerMethodField()
    submitted_at      = serializers.DateTimeField(source='created_at', format='%m/%d/%Y', read_only=True)
    can_edit          = serializers.SerializerMethodField()
    recurrence        = serializers.SerializerMethodField()
    next_due_date     = serializers.SerializerMethodField()
    total_occurrences = serializers.SerializerMethodField()
    location_name     = serializers.CharField(source='location.name', read_only=True)
    location_id       = serializers.IntegerField(read_only=True)

    class Meta:
        model  = Task
        fields = [
            'task_id', 'template_id', 'title', 'description',
            'location_id', 'location_name',
            'assignments', 'status_counts',
            'due_date', 'next_due_date', 'submitted_at',
            'is_recurring', 'frequency', 'recurrence', 'total_occurrences',
            'requires_photo',
            'can_edit',
        ]

    def get_template_id(self, obj):
        return obj.template_id

    def get_recurrence(self, obj):
        return _task_recurrence(obj)

    def get_next_due_date(self, obj):
        return obj.due_date if obj.template_id else None

    def get_total_occurrences(self, obj):
        if obj.template_id:
            meta = (self.context.get('series_meta') or {}).get(obj.template_id)
            if meta:
                return meta.get('total_occurrences', 1)
        return 1

    def get_assignments(self, obj):
        # Full assignment shape (same as the task-detail endpoint).
        return TaskAssignmentSerializer(obj.assignments.all(), many=True).data

    def get_status_counts(self, obj):
        return _series_status_counts(obj, self.context)

    def get_can_edit(self, obj):
        request = self.context.get('request')
        if request and request.user:
            has_pending = any(a.status == 'pending' for a in obj.assignments.all())
            return has_pending and obj.created_by_id == request.user.id
        return False

EMPLOYEE_NOTIFICATION_ROLES = ['tattoo_artist', 'body_piercer', 'staff']

# Full mesh: any admin role can notify any admin role (peers + upward).
# Employees are receive-only. The self-send block and the branch-manager
# own-location limit for employees are enforced separately in validate().
ADMIN_NOTIFICATION_ROLES = ['super_admin', 'district_manager', 'branch_manager']

ALLOWED_RECIPIENT_ROLES = {
    'super_admin':      ADMIN_NOTIFICATION_ROLES + EMPLOYEE_NOTIFICATION_ROLES,
    'district_manager': ADMIN_NOTIFICATION_ROLES + EMPLOYEE_NOTIFICATION_ROLES,
    'branch_manager':   ADMIN_NOTIFICATION_ROLES + EMPLOYEE_NOTIFICATION_ROLES,
}

class AdminNotificationCreateSerializer(serializers.Serializer):
    recipients = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        many=True
    )
    message = serializers.CharField(required=True, min_length=1)
    image   = serializers.ImageField(required=False, allow_null=True)

    def validate(self, data):
        sender  = self.context['request'].user
        allowed = ALLOWED_RECIPIENT_ROLES.get(sender.role, [])
        errors  = []
        for recipient in data['recipients']:
            if recipient == sender:
                errors.append(f"You cannot send a notification to yourself.")
            elif recipient.role not in allowed:
                errors.append(f"You cannot send to '{recipient.get_role_display()}' ({recipient.email}).")
            # branch managers can only notify employees at their own location
            elif (
                sender.role == 'branch_manager'
                and recipient.role in EMPLOYEE_NOTIFICATION_ROLES
                and recipient.location_id != sender.location_id
            ):
                errors.append(f"You can only send to employees at your own location ({recipient.email}).")
        if errors:
            raise serializers.ValidationError({"recipients": errors})
        return data


class AdminNotificationSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    sender_role = serializers.CharField(source='sender.role', read_only=True)

    class Meta:
        model  = AdminNotification
        fields = ['id', 'sender', 'sender_name', 'sender_role', 'message', 'image', 'created_at']
        read_only_fields = ['id', 'sender', 'created_at']

    def get_sender_name(self, obj):
        return f"{obj.sender.first_name} {obj.sender.last_name}".strip() or obj.sender.username


class AdminNotificationSentSerializer(serializers.ModelSerializer):
    recipients = serializers.SerializerMethodField()

    class Meta:
        model  = AdminNotification
        fields = ['id', 'message', 'image', 'created_at', 'recipients']

    def get_recipients(self, obj):
        return [
            {
                'id':   r.id,
                'name': f"{r.first_name} {r.last_name}".strip() or r.username,
                'role': r.get_role_display(),
            }
            for r in obj.recipients.all()
        ]

