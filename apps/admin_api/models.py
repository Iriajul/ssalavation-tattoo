# apps/admin_api/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone 


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

    def __str__(self):
        return self.name

    @property
    def staff_count(self):
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
    is_active  = models.BooleanField(default=False)   # toggle on/off
    start_time = models.TimeField(null=True, blank=True)
    end_time   = models.TimeField(null=True, blank=True)

    class Meta:
        db_table        = 'user_work_schedules'
        unique_together = ('user', 'day')
        ordering        = ['user']

    def __str__(self):
        return f"{self.user.email} - {self.get_day_display()}"
    

# ================================================================
# TASK
# ================================================================
 
class Task(models.Model):
 
    # ── Status ───────────────────────────────────────────────────
    STATUS_CHOICES = (
    ('pending',          'Pending'),
    ('completed',        'Completed'),
    ('awaiting_review',  'Awaiting Review'),  # ← new
    ('approved',         'Approved'),
    ('rejected',         'Rejected'),
    ('overdue',          'Overdue'),
)
 
    # ── Recurring frequency ───────────────────────────────────────
    FREQUENCY_CHOICES = (
        ('none',    'None'),
        ('daily',   'Daily'),
        ('weekly',  'Weekly'),
        ('monthly', 'Monthly'),
    )
 
    # ── Assignable roles (employees only) ─────────────────────────
    ASSIGNABLE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']
 
    # ── Core fields ───────────────────────────────────────────────
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
    due_date    = models.DateField()
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_fired = models.BooleanField(default=False)
 
    # ── Recurring ─────────────────────────────────────────────────
    is_recurring = models.BooleanField(default=False)
    frequency    = models.CharField(
        max_length=10,
        choices=FREQUENCY_CHOICES,
        default='none'
    )
 
    # ── Photo verification ────────────────────────────────────────
    requires_photo  = models.BooleanField(default=False)
    photo_url       = models.URLField(blank=True, null=True)   # Cloudinary URL
 
    # ── Completion & approval ─────────────────────────────────────
    completed_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='completed_tasks'
    )
    completed_at   = models.DateTimeField(null=True, blank=True)
    approved_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_tasks'
    )
    approved_at    = models.DateTimeField(null=True, blank=True)
 
    # ── Rejection ─────────────────────────────────────────────────
    rejection_reason = models.TextField(blank=True, null=True)
    rejected_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rejected_tasks'
    )
    rejected_at      = models.DateTimeField(null=True, blank=True)
 
    # ── Timestamps ────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        db_table = 'tasks'
        ordering = ['-created_at']
 
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
 
    # PDF stored on Cloudinary — save the URL
    pdf_url         = models.URLField(blank=True, null=True)
    pdf_filename    = models.CharField(max_length=255, blank=True, null=True)
 
    # Comma-separated roles e.g. "tattoo_artist,body_piercer"
    # Using CharField so no extra dependency needed
    role_visibility = models.JSONField(default=list)
 
    created_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_instructions'
    )
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
 
    class Meta:
        db_table = 'instructions'
        ordering = ['-created_at']
 
    def __str__(self):
        return self.title
 

class SplashScreen(models.Model):
    image_url  = models.URLField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'splash_screen'

    def __str__(self):
        return "Splash Screen"


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
    

class ActivityLog(models.Model):

    ACTION_CHOICES = (
        ('task_completed', 'Task Completed'),
        ('task_assigned',  'Task Assigned'),
        ('task_approved',  'Task Approved'),
        ('task_rejected',  'Task Rejected'),
        ('task_overdue',   'Task Overdue'),
        ('user_added',     'User Added'),
    )

    action       = models.CharField(max_length=30, choices=ACTION_CHOICES)
    actor        = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='activity_logs'
    )
    target_user  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='targeted_logs'
    )
    task         = models.ForeignKey(
        'Task',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='activity_logs'
    )
    message      = models.CharField(max_length=500)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'activity_logs'
        ordering = ['-created_at']

    def __str__(self):
        return self.message



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

    def __str__(self):
        return f"QR - {self.location.name} - {self.created_at}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def present_count(self):
        return self.attendances.filter(status='present').count()

    @property
    def late_count(self):
        return self.attendances.filter(status='late').count()

    @property
    def absent_count(self):
        return self.attendances.filter(status='absent').count()


class Attendance(models.Model):

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

    def __str__(self):
        return f"{self.user.email} - {self.date} - {self.status}"