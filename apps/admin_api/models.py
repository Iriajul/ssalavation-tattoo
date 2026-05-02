# apps/admin_api/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Count, Case, When, IntegerField,Q
from django.contrib.postgres.indexes import GinIndex

# ================================================================
# LOCATION
# ================================================================

class Location(models.Model):

    STATUS_CHOICES = (
        ('active',   'Active'),
        ('inactive', 'Inactive'),
    )

    name           = models.CharField(max_length=255)
    street_address = models.CharField(max_length=255)
    city_state     = models.CharField(max_length=255, blank=True, null=True)
    status         = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'locations'
        ordering = ['-created_at']
        indexes  = [
            # ── WHY: filtered by status='active' in almost every view
            models.Index(fields=['status'], name='location_status_idx'),
        ]

    def __str__(self):
        return self.name

    @property
    def staff_count(self):
        # WHY: using filter instead of count() on related manager
        # to avoid loading all objects into memory
        return self.users.filter(is_active=True).count()


# ================================================================
# WORK SCHEDULE
# ================================================================

class UserWorkSchedule(models.Model):

    DAY_CHOICES = (
        ('mon', 'Monday'),
        ('tue', 'Tuesday'),
        ('wed', 'Wednesday'),
        ('thu', 'Thursday'),
        ('fri', 'Friday'),
        ('sat', 'Saturday'),
        ('sun', 'Sunday'),
    )

    DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='work_schedules'
    )
    day        = models.CharField(max_length=3, choices=DAY_CHOICES)
    is_active  = models.BooleanField(default=False)
    start_time = models.TimeField(null=True, blank=True)
    end_time   = models.TimeField(null=True, blank=True)

    class Meta:
        db_table        = 'user_work_schedules'
        unique_together = ('user', 'day')
        ordering        = ['user']
        indexes         = [
            # ── WHY: always queried by user — prefetch_related uses this
            models.Index(fields=['user'], name='schedule_user_idx'),
            # ── WHY: composite — update_or_create uses (user, day) lookup
            models.Index(fields=['user', 'day'], name='schedule_user_day_idx'),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.get_day_display()}"


# ================================================================
# TASK
# ================================================================

class Task(models.Model):

    STATUS_CHOICES = (
        ('pending',          'Pending'),
        ('completed',        'Completed'),
        ('awaiting_review',  'Awaiting Review'),
        ('approved',         'Approved'),
        ('rejected',         'Rejected'),
        ('overdue',          'Overdue'),
    )

    FREQUENCY_CHOICES = (
        ('none',    'None'),
        ('daily',   'Daily'),
        ('weekly',  'Weekly'),
        ('monthly', 'Monthly'),
    )

    ASSIGNABLE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']

    title       = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    location    = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='tasks'
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='assigned_tasks'
    )
    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_tasks'
    )
    due_date     = models.DateField()
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_fired     = models.BooleanField(default=False)
    is_recurring = models.BooleanField(default=False)
    frequency    = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default='none')

    requires_photo = models.BooleanField(default=False)
    photo_url      = models.URLField(blank=True, null=True)

    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='completed_tasks'
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    approved_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_tasks'
    )
    approved_at      = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    rejected_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rejected_tasks'
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks'
        ordering = ['-created_at']
        indexes  = [
            # ── WHY: TaskViewSet filters by status constantly
            models.Index(fields=['status'], name='task_status_idx'),

            # ── WHY: filtered by location in branch manager views
            models.Index(fields=['location'], name='task_location_idx'),

            # ── WHY: filtered by assigned_to in employee task views
            models.Index(fields=['assigned_to'], name='task_assigned_to_idx'),

            # ── WHY: period filter uses created_at__date range
            models.Index(fields=['created_at'], name='task_created_at_idx'),

            # ── WHY: overdue detection compares due_date to today
            models.Index(fields=['due_date'], name='task_due_date_idx'),

            # ── WHY: most common combo — branch manager queries
            # filter(location=x, status='pending') constantly
            models.Index(fields=['location', 'status'], name='task_location_status_idx'),

            # ── WHY: super admin filters tasks by status + period together
            models.Index(fields=['status', 'created_at'], name='task_status_created_idx'),

            # ── WHY: assigned_to + status used in employee dashboard
            models.Index(fields=['assigned_to', 'status'], name='task_assigned_status_idx'),
        ]

    def __str__(self):
        return f"{self.title} → {self.assigned_to.email}"


# ================================================================
# INSTRUCTION
# ================================================================

class Instruction(models.Model):

    ROLE_CHOICES = (
        ('tattoo_artist', 'Tattoo Artist'),
        ('body_piercer',  'Body Piercer'),
        ('staff',         'Staff'),
    )

    title           = models.CharField(max_length=255)
    description     = models.TextField(blank=True, null=True)
    pdf_url         = models.URLField(blank=True, null=True)
    pdf_filename    = models.CharField(max_length=255, blank=True, null=True)
    role_visibility = models.JSONField(default=list)
    created_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_instructions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'instructions'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['created_at'], name='instruction_created_at_idx'),
            GinIndex(fields=['role_visibility'], name='instruct_role_vis_gin'),
        ]

    def __str__(self):
        return self.title


# ================================================================
# SPLASH SCREEN
# ================================================================

class SplashScreen(models.Model):
    web_image_url = models.URLField(blank=True, null=True)
    app_image_url = models.URLField(blank=True, null=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'splash_screen'

    def __str__(self):
        return "Splash Screen"


# ================================================================
# FAQ
# ================================================================

class FAQ(models.Model):
    question   = models.CharField(max_length=500)
    answer     = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'faqs'
        ordering = ['created_at']

    def __str__(self):
        return self.question


# ================================================================
# ACTIVITY LOG
# ================================================================

class ActivityLog(models.Model):

    ACTION_CHOICES = (
        ('task_completed',  'Task Completed'),
        ('task_assigned',   'Task Assigned'),
        ('task_approved',   'Task Approved'),
        ('task_rejected',   'Task Rejected'),
        ('task_overdue',    'Task Overdue'),
        ('user_added',      'User Added'),
        ('user_suspended',  'User Suspended'),
        ('user_activated',  'User Activated'),
    )

    action      = models.CharField(max_length=30, choices=ACTION_CHOICES)
    actor       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='activity_logs'
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='targeted_logs'
    )
    task        = models.ForeignKey(
        'Task',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='activity_logs'
    )
    message    = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'activity_logs'
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['created_at'], name='actlog_created_at_idx'),
            models.Index(fields=['action'],     name='actlog_action_idx'),
            # ── ADD THESE TWO ──
            models.Index(fields=['actor'],      name='actlog_actor_idx'),
            models.Index(fields=['target_user'],name='actlog_target_user_idx'),
        ]

    def __str__(self):
        return self.message


# ================================================================
# QR SESSION
# ================================================================

class QRSession(models.Model):

    INTERVAL_CHOICES = (
        (1,  'Every 1 minute'),
        (3,  'Every 3 minutes'),
        (5,  'Every 5 minutes'),
        (10, 'Every 10 minutes'),
        (30, 'Every 30 minutes'),
    )

    location         = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='qr_sessions'
    )
    created_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='qr_sessions'
    )
    token            = models.CharField(max_length=64, unique=True)
    refresh_interval = models.IntegerField(choices=INTERVAL_CHOICES, default=3)
    expires_at       = models.DateTimeField()
    is_active        = models.BooleanField(default=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'qr_sessions'
        ordering = ['-created_at']
        indexes  = [
            # ── WHY: QR lookup always checks is_active + location
            models.Index(fields=['is_active'], name='qr_is_active_idx'),
            models.Index(fields=['location', 'is_active'], name='qr_location_active_idx'),
            # ── WHY: token is used for QR scan lookup — unique already
            # creates index but explicit for clarity
            models.Index(fields=['token'], name='qr_token_idx'),
            # ── WHY: expiry check on every QR scan
            models.Index(fields=['expires_at'], name='qr_expires_at_idx'),
        ]

    def __str__(self):
        return f"QR - {self.location.name} - {self.created_at}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

# ================================================================
# ATTENDANCE
# ================================================================
class AttendanceQuerySet(models.QuerySet):

    def stats(self):
        return self.aggregate(
            present=Count(Case(When(status='present', then=1), output_field=IntegerField())),
            late=Count(Case(When(status='late', then=1), output_field=IntegerField())),
            absent=Count(Case(When(status='absent', then=1), output_field=IntegerField())),
        )

class Attendance(models.Model):
    objects = AttendanceQuerySet.as_manager()

    STATUS_CHOICES = (
        ('present', 'Present'),
        ('late',    'Late'),
        ('absent',  'Absent'),
    )

    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendances'
    )
    location   = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='attendances'
    )
    qr_session = models.ForeignKey(
        QRSession,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='attendances'
    )
    date       = models.DateField()
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES)
    clock_in   = models.TimeField(null=True, blank=True)
    clock_out  = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table        = 'attendances'
        unique_together = ('user', 'date')
        ordering        = ['-date']
        indexes         = [
            # ── WHY: most queried field — filter(date=today) everywhere
            models.Index(fields=['date'], name='attendance_date_idx'),

            # ── WHY: filter by status in reports and dashboard
            models.Index(fields=['status'], name='attendance_status_idx'),

            # ── WHY: filter by location in branch manager views
            models.Index(fields=['location'], name='attendance_location_idx'),

            # ── WHY: most common combo — dashboard queries filter(user, date)
            models.Index(fields=['user', 'date'], name='attendance_user_date_idx'),

            # ── WHY: reports filter by location + date range constantly
            models.Index(fields=['location', 'date'], name='attendance_location_date_idx'),

            # ── WHY: status + date used in attendance trend charts
            models.Index(fields=['status', 'date'], name='attendance_status_date_idx'),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.date} - {self.status}"


# ================================================================
# NOTIFICATION
# ================================================================

class Notification(models.Model):

    STATUS_CHOICES = (
        ('sent',   'Sent'),
        ('failed', 'Failed'),
    )

    sent_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sent_notifications'
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='received_notifications'
    )
    email    = models.EmailField()
    location = models.ForeignKey(
        'Location',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notifications'
    )
    message    = models.TextField()
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default='sent')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes  = [
            # ── WHY: stats query filters by status='sent'
            models.Index(fields=['status'], name='notif_status_idx'),
            # ── WHY: list ordered by created_at
            models.Index(fields=['created_at'], name='notif_created_at_idx'),
        ]

    def __str__(self):
        return f"Notification to {self.email} — {self.status}"