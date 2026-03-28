# apps/users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
import random
from datetime import timedelta
from django.utils import timezone


class User(AbstractUser):
    email = models.EmailField(unique=True, blank=False, null=False)

    ROLE_CHOICES = (
        ('super_admin',      'Super Admin'),
        ('district_manager', 'District Manager'),
        ('branch_manager',   'Branch Manager'),
        ('employee',         'Employee'),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='super_admin'
    )

    phone     = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    # Location assignment (null for super_admin / district_manager)
    location = models.ForeignKey(
        'admin_api.Location',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='users'
    )

    # OTP fields for password reset
    reset_otp        = models.CharField(max_length=6, blank=True, null=True)
    reset_otp_expiry = models.DateTimeField(blank=True, null=True)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users_user'

    def __str__(self):
        return f"{self.email} - {self.get_role_display()}"

    # ================== OTP Methods ==================
    def set_reset_otp(self):
        """Generate and save 5-digit OTP"""
        self.reset_otp = str(random.randint(10000, 99999))
        self.reset_otp_expiry = timezone.now() + timedelta(minutes=10)
        self.save(update_fields=['reset_otp', 'reset_otp_expiry'])
        return self.reset_otp

    def verify_reset_otp(self, otp):
        """Verify OTP and check expiry"""
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
        """Clear OTP after use or expiry"""
        self.reset_otp = None
        self.reset_otp_expiry = None
        self.save(update_fields=['reset_otp', 'reset_otp_expiry'])

    # ================== Role Helpers ==================
    def is_super_admin(self):
        return self.role == 'super_admin'

    def is_district_manager(self):
        return self.role == 'district_manager'

    def is_branch_manager(self):
        return self.role == 'branch_manager'

    def is_employee(self):
        return self.role == 'employee'