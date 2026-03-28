# apps/admin_api/models.py
from django.db import models


class Location(models.Model):

    STATUS_CHOICES = (
        ('active',   'Active'),
        ('inactive', 'Inactive'),
    )

    name           = models.CharField(max_length=255)               # Studio Name
    street_address = models.CharField(max_length=255)               # Street Address
    city_state     = models.CharField(max_length=255, blank=True, null=True)  # City, State
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
        """Total users assigned to this location"""
        return self.users.filter(is_active=True).count()