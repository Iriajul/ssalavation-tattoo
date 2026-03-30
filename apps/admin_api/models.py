# apps/admin_api/models.py
from django.db import models
from django.conf import settings


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
        ('pending',   'Pending'),
        ('completed', 'Completed'),
        ('approved',  'Approved'),
        ('rejected',  'Rejected'),
        ('overdue',   'Overdue'),
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
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
 
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
 