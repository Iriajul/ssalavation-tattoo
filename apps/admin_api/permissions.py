# apps/admin_api/permissions.py
from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """Allow access only to super_admin role"""
    message = "Access denied. Super Admin only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'super_admin'
        )


class IsBranchManager(BasePermission):
    """Allow access only to branch_manager role"""
    message = "Access denied. Branch Manager only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'branch_manager'
        )


class IsAdminUser(BasePermission):
    """Allow access to super_admin, district_manager, branch_manager"""
    message = "Access denied. Admin roles only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ['super_admin', 'district_manager', 'branch_manager']
        )


class IsAdminOrBranchManager(BasePermission):
    """Allow access to super_admin and branch_manager"""
    message = "Access denied. Super Admin or Branch Manager only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ['super_admin', 'branch_manager']
        )
    
class IsClockInUser(BasePermission):
    """Allow access only to clock_in_user role"""
    message = "Access denied. Clock In User only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'clock_in_user'
        )


