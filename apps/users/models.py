# apps/users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
import secrets
from datetime import timedelta
from django.utils import timezone


class User(AbstractUser):

    ROLE_CHOICES = (
        ('super_admin',      'Super Admin'),
        ('district_manager', 'District Manager'),
        ('branch_manager',   'Branch Manager'),
        ('tattoo_artist',    'Tattoo Artist'),
        ('body_piercer',     'Body Piercer'),
        ('staff',            'Staff'),
        ('clock_in_user',    'Clock In User'),
    )

    email         = models.EmailField(unique=True, blank=False, null=False)
    role          = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')
    phone         = models.CharField(max_length=20, blank=True, null=True)
    profile_photo = models.URLField(blank=True, null=True)
    last_login_at = models.DateTimeField(blank=True, null=True)
    is_active     = models.BooleanField(default=True)
    is_suspended  = models.BooleanField(default=False)

    location = models.ForeignKey(
        'admin_api.Location',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='users'
    )

    # ── OTP fields ────────────────────────────────────────────────
    reset_otp        = models.CharField(max_length=6, blank=True, null=True)
    reset_otp_expiry = models.DateTimeField(blank=True, null=True)
    login_otp        = models.CharField(max_length=5, blank=True, null=True)
    login_otp_expiry = models.DateTimeField(blank=True, null=True)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users_user'
        indexes  = [
            # ── WHY: role is filtered in almost every view
            # UserViewSet, DashboardView, BranchManagerDashboardView all filter by role
            models.Index(fields=['role'], name='user_role_idx'),

            # ── WHY: is_active filtered everywhere — suspended/active checks
            models.Index(fields=['is_active'], name='user_is_active_idx'),

            # ── WHY: location filtered in branch manager views
            # filter(location=manager.location, role__in=EMPLOYEE_ROLES)
            models.Index(fields=['location'], name='user_location_idx'),

            # ── WHY: most common combo in your code
            # User.objects.filter(role__in=EMPLOYEE_ROLES, is_active=True)
            models.Index(fields=['role', 'is_active'], name='user_role_active_idx'),

            # ── WHY: branch manager queries filter(location=x, role__in=y, is_active=True)
            models.Index(fields=['location', 'role'], name='user_location_role_idx'),

            # ── WHY: composite — most specific filter used in assignment dropdown
            models.Index(fields=['location', 'role', 'is_active'], name='user_location_role_active_idx'),

            # ── WHY: is_suspended checked on login and in user list
            models.Index(fields=['is_suspended'], name='user_is_suspended_idx'),
        ]

    def __str__(self):
        return f"{self.email} - {self.get_role_display()}"

    @property
    def is_app_user(self):
        return self.role in ['tattoo_artist', 'body_piercer', 'staff']

    @property
    def needs_schedule(self):
        return self.role in ['tattoo_artist', 'body_piercer', 'staff']

    # ================================================================
    # LOGIN OTP METHODS
    # ================================================================

    def set_login_otp(self):
        self.login_otp        = str(secrets.randbelow(90000) + 10000)  # ← cryptographically secure
        self.login_otp_expiry = timezone.now() + timedelta(minutes=10)
        self.save(update_fields=['login_otp', 'login_otp_expiry'])
        return self.login_otp

    def verify_login_otp(self, otp):
        if not self.login_otp or not self.login_otp_expiry:
            return False
        if timezone.now() > self.login_otp_expiry:
            self.clear_login_otp()
            return False
        if self.login_otp == otp:
            self.clear_login_otp()
            return True
        return False

    def clear_login_otp(self):
        self.login_otp        = None
        self.login_otp_expiry = None
        self.save(update_fields=['login_otp', 'login_otp_expiry'])

    # ================================================================
    # RESET OTP METHODS
    # ================================================================

    def set_reset_otp(self):
        self.reset_otp        = str(secrets.randbelow(90000) + 10000)  # ← cryptographically secure
        self.reset_otp_expiry = timezone.now() + timedelta(minutes=10)
        self.save(update_fields=['reset_otp', 'reset_otp_expiry'])
        return self.reset_otp

    def verify_reset_otp(self, otp):
        if not self.reset_otp or not self.reset_otp_expiry:
            return False
        if timezone.now() > self.reset_otp_expiry:
            self.clear_reset_otp()
            return False
        if self.reset_otp == otp:
            self.clear_reset_otp()
            return True
        return False

    def clear_reset_otp(self):
        self.reset_otp        = None
        self.reset_otp_expiry = None
        self.save(update_fields=['reset_otp', 'reset_otp_expiry'])

    # ================================================================
    # ROLE HELPERS
    # ================================================================

    def is_super_admin(self):
        return self.role == 'super_admin'

    def is_district_manager(self):
        return self.role == 'district_manager'

    def is_branch_manager(self):
        return self.role == 'branch_manager'