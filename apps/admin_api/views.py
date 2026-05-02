# apps/admin_api/views.py
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.pagination import PageNumberPagination
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.utils.timesince import timesince
from datetime import timedelta
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from django.db.models import Prefetch, Q, Count, Case, When, IntegerField
import secrets

from .models import (
    FAQ, Attendance, Location, QRSession,
    SplashScreen, UserWorkSchedule, Task,
    Instruction, ActivityLog, Notification
)
from .permissions import IsBranchManager, IsSuperAdmin, IsClockInUser
from .serializers import (
    AdminChangePasswordSerializer,
    AdminProfileSerializer,
    AttendanceSerializer,
    BranchManagerTaskCreateSerializer,
    BranchManagerTaskListSerializer,
    CustomTokenObtainPairSerializer,
    FAQSerializer,
    ForgotPasswordSerializer,
    QRSessionListSerializer,
    QRSessionSerializer,
    SplashScreenSerializer,
    VerifyResetOTPSerializer,
    ResetPasswordSerializer,
    LocationSerializer,
    LocationListSerializer,
    LocationStatsSerializer,
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    UserStatsSerializer,
    TaskListSerializer,
    TaskDetailSerializer,
    TaskCreateSerializer,
    TaskUpdateSerializer,
    TaskRejectSerializer,
    TaskStatsSerializer,
    FireUserSerializer,           # ← was missing from imports
    LocationEmployeeSerializer,
    InstructionSerializer,
    InstructionListSerializer,
    InstructionStatsSerializer,
    NotificationCreateSerializer,
    NotificationSerializer,
    NotificationStatsSerializer,
)

User = get_user_model()

EMPLOYEE_ROLES   = ['tattoo_artist', 'body_piercer', 'staff']
ASSIGNABLE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']


# ================================================================
# AUTH VIEWS
# ================================================================

class AdminLoginView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = CustomTokenObtainPairSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class ForgotPasswordView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        user  = User.objects.get(email=email)
        otp   = user.set_reset_otp()

        try:
            send_mail(
                subject        = "Salvation Tattoo Admin Password Reset Code",
                message        = f"Your 5-digit reset code is: {otp}\n\nThis code will expire in 10 minutes.",
                from_email     = settings.DEFAULT_FROM_EMAIL,
                recipient_list = [email],
                fail_silently  = False,
            )
        except Exception as e:
            print(f"Email sending failed: {e}")

        refresh = RefreshToken.for_user(user)
        refresh.access_token.set_exp(lifetime=timedelta(minutes=15))

        return Response({
            "message":    "Reset code sent to your email.",
            "temp_token": str(refresh.access_token),
        }, status=status.HTTP_200_OK)


class VerifyResetOTPView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = VerifyResetOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token = serializer.validated_data['temp_token']
        otp        = serializer.validated_data['otp']

        try:
            untyped_token = UntypedToken(temp_token)
            user_id       = untyped_token.payload.get('user_id')
            user          = User.objects.get(id=user_id)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired temporary token"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.verify_reset_otp(otp):
            return Response(
                {"error": "Invalid or expired OTP"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "message": "OTP verified successfully. You can now set a new password."
        }, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token   = serializer.validated_data['temp_token']
        new_password = serializer.validated_data['new_password']

        try:
            untyped_token = UntypedToken(temp_token)
            user_id       = untyped_token.payload.get('user_id')
            user          = User.objects.get(id=user_id)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired temporary token"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        user.set_password(new_password)
        user.save(update_fields=['password'])

        return Response({
            "message": "Password reset successfully. Please login with your new password."
        }, status=status.HTTP_200_OK)


# ================================================================
# LOCATION VIEWSET
# ================================================================

class LocationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    queryset           = Location.objects.all().order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return LocationListSerializer
        return LocationSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # FIX: single aggregate query instead of 3 separate counts
        stats_data = queryset.aggregate(
            total_locations  = Count('id'),
            active_locations = Count(Case(When(status='active', then=1), output_field=IntegerField())),
        )
        total_staff = User.objects.filter(is_active=True, location__isnull=False).count()

        stats = LocationStatsSerializer({
            'total_locations':  stats_data['total_locations'],
            'total_staff':      total_staff,
            'active_locations': stats_data['active_locations'],
        }).data

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'stats':     stats,
            'locations': serializer.data,
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        location = serializer.save()
        return Response({
            'message':  'Location created successfully.',
            'location': LocationSerializer(location).data,
        }, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        location   = self.get_object()
        serializer = self.get_serializer(location, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        location = serializer.save()
        return Response({
            'message':  'Location updated successfully.',
            'location': LocationSerializer(location).data,
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        location = self.get_object()
        User.objects.filter(location=location).update(location=None)
        location.delete()
        return Response(
            {"message": "Location deleted successfully."},
            status=status.HTTP_200_OK
        )


# ================================================================
# USER VIEWSET
# ================================================================

class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    filter_backends    = [SearchFilter]
    search_fields      = ['first_name', 'last_name', 'username', 'email', 'role']

    def get_queryset(self):
        return User.objects.exclude(
            role='super_admin'
        ).select_related('location').prefetch_related('work_schedules').order_by('-date_joined')

    def get_serializer_class(self):
        if self.action == 'list':
            return UserListSerializer
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserDetailSerializer

    def list(self, request, *args, **kwargs):
        queryset  = self.filter_queryset(self.get_queryset())

        # FIX: single aggregate query instead of 3 separate counts
        all_users  = User.objects.exclude(role='super_admin')
        stats_data = all_users.aggregate(
            district_managers = Count(Case(When(role='district_manager', then=1), output_field=IntegerField())),
            managers          = Count(Case(When(role='branch_manager',   then=1), output_field=IntegerField())),
            employees         = Count(Case(When(role__in=EMPLOYEE_ROLES, then=1), output_field=IntegerField())),
        )
        stats = UserStatsSerializer(stats_data).data

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated  = self.get_paginated_response(serializer.data)
            return Response({
                'stats': stats,
                'users': paginated.data,
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'stats': stats,
            'users': serializer.data,
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        ActivityLog.objects.create(
            action      = 'user_added',
            actor       = request.user,
            target_user = user,
            message     = f'New employee {user.get_full_name()} added to {user.location.name if user.location else "no location"}'
        )

        return Response({
            'message': 'User created successfully.',
            'user':    UserDetailSerializer(user).data,
        }, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        user = self.get_object()
        return Response(UserDetailSerializer(user).data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        user       = self.get_object()
        serializer = self.get_serializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        sent_days = [
            s['day'] for s in request.data.get('work_schedules', [])
        ] if 'work_schedules' in request.data else None

        schedule_qs = (
            UserWorkSchedule.objects.filter(day__in=sent_days)
            if sent_days is not None
            else UserWorkSchedule.objects.none()
        )

        user = User.objects.prefetch_related(
            Prefetch('work_schedules', queryset=schedule_qs)
        ).get(pk=user.pk)

        return Response({
            'message': 'User updated successfully.',
            'user':    UserDetailSerializer(user).data,
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        user.delete()
        return Response(
            {"message": "User deleted successfully."},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='suspend')
    def suspend(self, request, pk=None):
        user = self.get_object()

        if user.is_suspended:
            return Response(
                {"error": "User is already suspended."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_suspended = True
        user.is_active    = False
        user.save(update_fields=['is_suspended', 'is_active'])

        ActivityLog.objects.create(
            action      = 'user_suspended',
            actor       = request.user,
            target_user = user,
            message     = f'{user.get_full_name()} has been suspended by {request.user.get_full_name()}'
        )

        return Response({
            "message": f"{user.get_full_name()} has been suspended.",
            "user":    UserDetailSerializer(user).data,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        user = self.get_object()

        if user.is_active and not user.is_suspended:
            return Response(
                {"error": "User is already active."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_suspended = False
        user.is_active    = True
        user.save(update_fields=['is_suspended', 'is_active'])

        ActivityLog.objects.create(
            action      = 'user_activated',
            actor       = request.user,
            target_user = user,
            message     = f'{user.get_full_name()} has been activated by {request.user.get_full_name()}'
        )

        return Response({
            "message": f"{user.get_full_name()} has been activated.",
            "user":    UserDetailSerializer(user).data,
        }, status=status.HTTP_200_OK)


# ================================================================
# TASK VIEWSET
# ================================================================

class TaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    filter_backends    = [SearchFilter]
    search_fields      = [
        'title', 'description',
        'assigned_to__first_name', 'assigned_to__last_name',
        'completed_by__first_name', 'completed_by__last_name',
    ]

    def get_queryset(self):
        queryset = Task.objects.select_related(
            'location', 'assigned_to', 'completed_by',
            'approved_by', 'rejected_by', 'created_by'
        ).order_by('-created_at')

        status_filter   = self.request.query_params.get('status')
        location_filter = self.request.query_params.get('location')
        period_filter   = self.request.query_params.get('period')

        if status_filter and status_filter != 'all':
            queryset = queryset.filter(status=status_filter)

        if location_filter and location_filter != 'all':
            queryset = queryset.filter(location_id=location_filter)

        if period_filter and period_filter != 'all':
            today = timezone.localdate()
            if period_filter == 'today':
                queryset = queryset.filter(created_at__date=today)
            elif period_filter == 'weekly':
                queryset = queryset.filter(created_at__date__gte=today - timedelta(days=7))
            elif period_filter == 'monthly':
                queryset = queryset.filter(created_at__date__gte=today - timedelta(days=30))
            elif period_filter == 'yearly':
                queryset = queryset.filter(created_at__date__gte=today - timedelta(days=365))

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return TaskListSerializer
        if self.action == 'create':
            return TaskCreateSerializer
        if self.action in ['update', 'partial_update']:
            return TaskUpdateSerializer
        return TaskDetailSerializer

    def list(self, request, *args, **kwargs):
        queryset     = self.filter_queryset(self.get_queryset())
        search_query = request.query_params.get('search', '').strip()

        # FIX: single aggregate query instead of 4 separate counts
        stats_data = Task.objects.aggregate(
            all_tasks = Count('id'),
            overdue   = Count(Case(When(status='overdue',   then=1), output_field=IntegerField())),
            completed = Count(Case(When(status='completed', then=1), output_field=IntegerField())),
            rejected  = Count(Case(When(status='rejected',  then=1), output_field=IntegerField())),
        )
        stats = TaskStatsSerializer(stats_data).data

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer    = self.get_serializer(page, many=True)
            paginated      = self.get_paginated_response(serializer.data)
            response_data  = {'tasks': paginated.data}
            if not search_query:
                response_data['stats'] = stats
            return Response(response_data, status=status.HTTP_200_OK)

        serializer    = self.get_serializer(queryset, many=True)
        response_data = {'tasks': serializer.data}
        if not search_query:
            response_data['stats'] = stats
        return Response(response_data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(created_by=request.user)

        ActivityLog.objects.create(
            action      = 'task_assigned',
            actor       = request.user,
            task        = task,
            target_user = task.assigned_to,
            message     = f'Task "{task.title}" assigned to {task.assigned_to.get_full_name()}'
        )

        return Response({
            'message': 'Task created successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        task = self.get_object()
        return Response(TaskDetailSerializer(task).data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        task = self.get_object()
        # FIX: super admin can edit any pending task — removed wrong created_by check
        if task.status != 'pending':
            return Response(
                {"error": "Only pending tasks can be edited."},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = self.get_serializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response({
            'message': 'Task updated successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        task = self.get_object()
        # FIX: super admin can delete any pending task — removed wrong created_by check
        if task.status != 'pending':
            return Response(
                {"error": "Only pending tasks can be deleted."},
                status=status.HTTP_400_BAD_REQUEST
            )
        task.delete()
        return Response(
            {"message": "Task deleted successfully."},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        task = self.get_object()

        if task.status not in ['awaiting_review', 'rejected']:
            return Response(
                {"error": "Only awaiting review or rejected tasks can be approved."},
                status=status.HTTP_400_BAD_REQUEST
            )

        task.status           = 'approved'
        task.approved_by      = request.user
        task.approved_at      = timezone.now()
        task.rejection_reason = None
        task.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason'])

        ActivityLog.objects.create(
            action      = 'task_approved',
            actor       = request.user,
            task        = task,
            target_user = task.assigned_to,
            message     = f'Task "{task.title}" approved for {task.assigned_to.get_full_name()}'
        )

        return Response({
            'message': 'Task approved successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        task       = self.get_object()
        serializer = TaskRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if task.status not in ['awaiting_review', 'approved']:
            return Response(
                {"error": "Only awaiting review or approved tasks can be rejected."},
                status=status.HTTP_400_BAD_REQUEST
            )

        task.status           = 'rejected'
        task.rejected_by      = request.user
        task.rejected_at      = timezone.now()
        task.rejection_reason = serializer.validated_data['rejection_reason']
        task.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason'])

        ActivityLog.objects.create(
            action      = 'task_rejected',
            actor       = request.user,
            task        = task,
            target_user = task.assigned_to,
            message     = f'Task "{task.title}" rejected — {serializer.validated_data["rejection_reason"]}'
        )

        return Response({
            'message': 'Task rejected.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='fire-info')
    def fire_info(self, request, pk=None):
        task = self.get_object()
        if task.status != 'overdue':
            return Response(
                {"error": "This task is not overdue."},
                status=status.HTTP_400_BAD_REQUEST
            )
        user = task.assigned_to
        return Response({
            'task_id':       task.id,
            'task_title':    task.title,
            'employee_name': user.get_full_name(),
            'email':         user.email,
            'role':          user.get_role_display(),
            'location':      user.location.name if user.location else None,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='fire-user')
    def fire_user(self, request, pk=None):
        task = self.get_object()

        if task.status != 'overdue':
            return Response(
                {"error": "You can only fire an employee for an overdue task."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if task.is_fired:
            return Response(
                {"error": "This employee has already been fired for this task."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = FireUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        fire_reason = serializer.validated_data['fire_reason']
        user        = task.assigned_to

        task.is_fired = True
        task.save(update_fields=['is_fired'])

        user.is_active    = False
        user.is_suspended = True
        user.save(update_fields=['is_active', 'is_suspended'])

        try:
            send_mail(
                subject        = "Employment Termination — Salvation Tattoo Lounge",
                message        = (
                    f"Dear {user.get_full_name()},\n\n"
                    f"We regret to inform you that your employment at Salvation Tattoo Lounge "
                    f"has been terminated.\n\n"
                    f"Reason: {fire_reason}\n\n"
                    f"Please contact management if you have any questions.\n\n"
                    f"Salvation Tattoo Lounge Management"
                ),
                from_email     = settings.DEFAULT_FROM_EMAIL,
                recipient_list = [user.email],
                fail_silently  = False,
            )
        except Exception as e:
            print(f"Fire email failed: {e}")

        ActivityLog.objects.create(
            action      = 'user_suspended',
            actor       = request.user,
            target_user = user,
            message     = f'{user.get_full_name()} was fired. Reason: {fire_reason}'
        )

        return Response({
            'message':     f'{user.get_full_name()} has been fired and notified by email.',
            'employee':    {
                'id':    user.id,
                'name':  user.get_full_name(),
                'email': user.email,
            },
            'fire_reason': fire_reason,
        }, status=status.HTTP_200_OK)


# ================================================================
# EMPLOYEES BY LOCATION
# ================================================================

class LocationEmployeesView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        try:
            location = Location.objects.get(pk=pk)
        except Location.DoesNotExist:
            return Response(
                {"error": "Location not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        employees = User.objects.filter(
            location  = location,
            role__in  = ASSIGNABLE_ROLES,
            is_active = True
        )

        serializer = LocationEmployeeSerializer(employees, many=True)
        return Response({
            'location':  location.name,
            'employees': serializer.data,
        }, status=status.HTTP_200_OK)


# ================================================================
# INSTRUCTION VIEWSET
# ================================================================

class InstructionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    filter_backends    = [SearchFilter]
    search_fields      = ['title', 'description']
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        queryset    = Instruction.objects.all().order_by('-created_at')
        role_filter = self.request.query_params.get('role')
        if role_filter and role_filter != 'all':
            queryset = queryset.filter(role_visibility__contains=role_filter)
        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return InstructionListSerializer
        return InstructionSerializer

    def _parse_role_visibility(self, request):
        import json
        role_visibility = request.data.getlist('role_visibility')
        if not role_visibility:
            return []
        if len(role_visibility) == 1:
            try:
                parsed = json.loads(role_visibility[0])
                if isinstance(parsed, list):
                    return parsed
            except (ValueError, TypeError):
                pass
        return role_visibility

    def list(self, request, *args, **kwargs):
        queryset     = self.filter_queryset(self.get_queryset())
        all_instruct = Instruction.objects.all()
        role_filter  = request.query_params.get('role')

        # NOTE: JSONField contains queries can use aggregate easily
        stats_data = Instruction.objects.aggregate(
            total_instructions = Count('id'),
            tattoo_artists     = Count('id', filter=Q(role_visibility__contains=['tattoo_artist'])),
            body_piercers      = Count('id', filter=Q(role_visibility__contains=['body_piercer'])),
            staff              = Count('id', filter=Q(role_visibility__contains=['staff'])),
            branch_managers    = Count('id', filter=Q(role_visibility__contains=['branch_manager'])),
            district_managers  = Count('id', filter=Q(role_visibility__contains=['district_manager'])),
        )
        stats = InstructionStatsSerializer(stats_data).data

        serializer = self.get_serializer(queryset, many=True)
        all_data   = serializer.data

        if role_filter and role_filter != 'all':
            return Response({
                'stats':        stats,
                'instructions': all_data,
            }, status=status.HTTP_200_OK)

        employee_instructions         = [i for i in all_data if any(r in i['role_visibility'] for r in ['tattoo_artist', 'body_piercer', 'staff'])]
        manager_instructions          = [i for i in all_data if 'branch_manager'   in i['role_visibility']]
        district_manager_instructions = [i for i in all_data if 'district_manager' in i['role_visibility']]

        grouped = [
            {'section': 'Employees Instructions',         'document_count': len(employee_instructions),         'instructions': employee_instructions},
            {'section': 'Managers Instructions',          'document_count': len(manager_instructions),          'instructions': manager_instructions},
            {'section': 'District Managers Instructions', 'document_count': len(district_manager_instructions), 'instructions': district_manager_instructions},
        ]

        return Response({
            'stats':   stats,
            'grouped': grouped,
        }, status=status.HTTP_200_OK)

    # FIX: duplicate create method removed — only keep this one
    def create(self, request, *args, **kwargs):
        role_visibility = self._parse_role_visibility(request)
        data = {
            'title':           request.data.get('title'),
            'description':     request.data.get('description', ''),
            'role_visibility': role_visibility,
        }
        if 'pdf_file' in request.FILES:
            data['pdf_file'] = request.FILES['pdf_file']

        serializer = InstructionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        instruction = serializer.save(created_by=request.user)

        return Response({
            'message':     'Instruction created successfully.',
            'instruction': InstructionSerializer(instruction).data,
        }, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instruction     = self.get_object()
        role_visibility = self._parse_role_visibility(request)
        data = {}
        if request.data.get('title'):
            data['title'] = request.data.get('title')
        if request.data.get('description'):
            data['description'] = request.data.get('description')
        if role_visibility:
            data['role_visibility'] = role_visibility
        if 'pdf_file' in request.FILES:
            data['pdf_file'] = request.FILES['pdf_file']

        serializer = InstructionSerializer(instruction, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        instruction = serializer.save()

        return Response({
            'message':     'Instruction updated successfully.',
            'instruction': InstructionSerializer(instruction).data,
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instruction = self.get_object()
        instruction.delete()
        return Response(
            {"message": "Instruction deleted successfully."},
            status=status.HTTP_200_OK
        )


# ================================================================
# APP CONTENT
# ================================================================

class SplashScreenView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        obj = SplashScreen.objects.first()
        return Response(SplashScreenSerializer(obj).data if obj else {
            "web_image_url": None,
            "app_image_url": None,
        })

    def post(self, request):
        import cloudinary.uploader
        image_type = request.data.get('type')
        image      = request.FILES.get('image')

        if not image:
            return Response({"error": "No image provided."}, status=status.HTTP_400_BAD_REQUEST)
        if image_type not in ['web', 'app']:
            return Response({"error": "type must be 'web' or 'app'"}, status=status.HTTP_400_BAD_REQUEST)

        result = cloudinary.uploader.upload(image, folder="splash_screen")
        obj, _ = SplashScreen.objects.get_or_create(id=1)

        if image_type == 'web':
            obj.web_image_url = result['secure_url']
        else:
            obj.app_image_url = result['secure_url']
        obj.save()

        return Response({
            "message":   f"{'Website' if image_type == 'web' else 'App'} splash screen updated.",
            "image_url": result['secure_url'],
            "type":      image_type,
        })


class FAQViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    serializer_class   = FAQSerializer
    queryset           = FAQ.objects.all()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        faq = serializer.save()
        return Response({"message": "FAQ created.", "faq": FAQSerializer(faq).data}, status=201)

    def update(self, request, *args, **kwargs):
        faq        = self.get_object()
        serializer = self.get_serializer(faq, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        faq = serializer.save()
        return Response({"message": "FAQ updated.", "faq": FAQSerializer(faq).data})

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return Response({"message": "FAQ deleted."})


# ================================================================
# PROFILE
# ================================================================

class AdminProfileView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        return Response(AdminProfileSerializer(request.user).data)

    def patch(self, request):
        photo = request.FILES.get('profile_photo')
        if photo:
            import cloudinary.uploader
            result = cloudinary.uploader.upload(photo, folder="profile_photos")
            request.user.profile_photo = result['secure_url']
            request.user.save(update_fields=['profile_photo'])
            return Response({
                "message":       "Profile photo updated.",
                "profile_photo": request.user.profile_photo,
            })
        return Response({"error": "No photo provided."}, status=400)


class AdminChangePasswordView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        serializer = AdminChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(serializer.validated_data['current_password']):
            return Response(
                {"error": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])

        tokens = OutstandingToken.objects.filter(user=user)
        for token in tokens:
            BlacklistedToken.objects.get_or_create(token=token)

        return Response({"message": "Password updated successfully. Please login again."})


# ================================================================
# PERFORMANCE
# ================================================================

def get_performance_status(completion_rate):
    if completion_rate >= 90:
        return 'Good'
    elif completion_rate >= 75:
        return 'Monitor'
    return 'At Risk'

class PerformanceAnalyticsView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        period = request.query_params.get('period', 'today')
        now    = timezone.now()

        if period == 'today':
            start_date     = now.replace(hour=0, minute=0, second=0, microsecond=0)
            days_in_period = 1
        elif period == 'monthly':
            start_date     = now - timedelta(days=30)
            days_in_period = 30
        elif period == 'yearly':
            start_date     = now - timedelta(days=365)
            days_in_period = 365
        else:
            start_date     = now - timedelta(days=7)
            days_in_period = 7

        employees = User.objects.filter(role__in=EMPLOYEE_ROLES, is_active=True)

        # ── Compute once — reuse everywhere ───────────────────────
        total_emp = employees.count()

        employees_with_attendance = employees.prefetch_related(
            Prefetch(
                'attendances',
                queryset=Attendance.objects.filter(
                    date__gte  = start_date.date(),
                    status__in = ['present', 'late']
                ),
                to_attr='period_attendances'
            )
        )

        # ── Bulk task stats — 1 query for all employees ───────────
        emp_ids = list(employees.values_list('id', flat=True))

        task_bulk_qs = (
            Task.objects
            .filter(assigned_to_id__in=emp_ids, created_at__gte=start_date)
            .values('assigned_to_id')
            .annotate(
                total     = Count('id'),
                completed = Count(Case(
                    When(status__in=['completed', 'approved'], then=1),
                    output_field=IntegerField()
                )),
                overdue   = Count(Case(
                    When(status='overdue', then=1),
                    output_field=IntegerField()
                )),
            )
        )
        task_bulk_map = {row['assigned_to_id']: row for row in task_bulk_qs}

        rankings = []
        for employee in employees_with_attendance:
            task_data       = task_bulk_map.get(employee.id, {})
            total           = task_data.get('total',     0)
            completed       = task_data.get('completed', 0)
            overdue         = task_data.get('overdue',   0)
            completion_rate = round((completed / total * 100)) if total > 0 else 0
            overdue_penalty = (overdue / total * 100) if total > 0 else 0
            perf_score      = round((completion_rate * 0.7) + ((100 - overdue_penalty) * 0.3))

            emp_attended   = len(employee.period_attendances)
            emp_attendance = round((emp_attended / days_in_period * 100)) if days_in_period > 0 else 0

            rankings.append({
                'user':              employee,
                'tasks_completed':   completed,
                'total_tasks':       total,
                'overdue':           overdue,
                'completion_rate':   completion_rate,
                'performance_score': perf_score,
                'attendance':        emp_attendance,
                'status':            get_performance_status(completion_rate),
            })

        rankings.sort(key=lambda x: x['performance_score'], reverse=True)

        top_performer = None
        if rankings:
            top = rankings[0]
            top_performer = {
                'id':                top['user'].id,
                'name':              f"{top['user'].first_name} {top['user'].last_name}".strip(),
                'email':             top['user'].email,
                'performance_score': top['performance_score'],
                'tasks_completed':   top['tasks_completed'],
                'completion_rate':   top['completion_rate'],
                'attendance':        top['attendance'],
            }

        total_completed = sum(r['tasks_completed'] for r in rankings)
        avg_completion  = round(sum(r['completion_rate'] for r in rankings) / len(rankings)) if rankings else 0

        # ── Attendance avg — reuses total_emp, no extra count() ───
        total_attended = Attendance.objects.filter(
            user__in   = employees,
            date__gte  = start_date.date(),
            status__in = ['present', 'late']
        ).count()
        max_possible   = total_emp * days_in_period
        avg_attendance = round((total_attended / max_possible * 100)) if max_possible > 0 else 0

        ranked_list = []
        for i, r in enumerate(rankings, start=1):
            ranked_list.append({
                'rank':              i,
                'id':                r['user'].id,
                'name':              f"{r['user'].first_name} {r['user'].last_name}".strip(),
                'email':             r['user'].email,
                'tasks_completed':   r['tasks_completed'],
                'overdue':           r['overdue'],
                'completion_rate':   r['completion_rate'],
                'performance_score': r['performance_score'],
                'attendance':        r['attendance'],
                'status':            r['status'],
            })

        paginator      = PageNumberPagination()
        page           = paginator.paginate_queryset(ranked_list, request)
        paginated_data = paginator.get_paginated_response(page).data

        return Response({
            'period': period,
            'stats': {
                'avg_completion_rate':   avg_completion,
                'avg_attendance_rate':   avg_attendance,
                'total_tasks_completed': total_completed,
                'active_employees':      total_emp,       # reused — no extra query
            },
            'top_performer': top_performer,
            'rankings':      paginated_data,
        })
# ================================================================
# REPORTS
# ================================================================
class ReportsAnalyticsView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        from dateutil.relativedelta import relativedelta

        period          = request.query_params.get('period', 'today')
        location_filter = request.query_params.get('location')
        user_filter     = request.query_params.get('user')
        now             = timezone.now()

        if period == 'today':
            start_date     = now.replace(hour=0, minute=0, second=0, microsecond=0)
            days_in_period = 1
        elif period == 'monthly':
            start_date     = now - timedelta(days=30)
            days_in_period = 30
        elif period == 'yearly':
            start_date     = now - timedelta(days=365)
            days_in_period = 365
        else:
            start_date     = now - timedelta(days=7)
            days_in_period = 7

        # ── Base querysets ────────────────────────────────────────
        tasks = Task.objects.filter(created_at__gte=start_date)
        if location_filter:
            tasks = tasks.filter(location_id=location_filter)
        if user_filter:
            tasks = tasks.filter(assigned_to_id=user_filter)

        # ── Top stats ─────────────────────────────────────────────
        task_stats = tasks.aggregate(
            total     = Count('id'),
            completed = Count(Case(When(status__in=['completed', 'approved'], then=1), output_field=IntegerField())),
            pending   = Count(Case(When(status='pending', then=1), output_field=IntegerField())),
        )
        total_tasks     = task_stats['total']
        completed_tasks = task_stats['completed']
        pending_tasks   = task_stats['pending']
        completion_rate = round((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0
        active_staff    = User.objects.filter(role__in=EMPLOYEE_ROLES, is_active=True).count()

        total_employees = active_staff
        total_attended  = Attendance.objects.filter(
            date__gte  = start_date.date(),
            status__in = ['present', 'late']
        ).count()
        max_possible   = total_employees * days_in_period
        avg_attendance = round((total_attended / max_possible * 100)) if max_possible > 0 else 0

        # ── Attendance trend chart ────────────────────────────────
        attendance_trend = []

        if period == 'yearly':
            # Build all 12 month boundaries first
            month_ranges = []
            for i in range(11, -1, -1):
                m_start = (now - relativedelta(months=i)).replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                m_end = m_start + relativedelta(months=1)
                month_ranges.append((m_start, m_end))

            year_start = month_ranges[0][0].date()
            year_end   = month_ranges[-1][1].date()

            # 1 query — all attendance in the year grouped by date+status
            att_qs = (
                Attendance.objects
                .filter(date__gte=year_start, date__lt=year_end)
                .values('date', 'status')
                .annotate(total=Count('id'))
            )
            # Build lookup: { date: { status: count } }
            att_map = {}
            for row in att_qs:
                att_map.setdefault(row['date'], {})[row['status']] = row['total']

            for m_start, m_end in month_ranges:
                present = late = absent = 0
                d = m_start.date()
                while d < m_end.date():
                    day_data = att_map.get(d, {})
                    present += day_data.get('present', 0)
                    late    += day_data.get('late',    0)
                    absent  += day_data.get('absent',  0)
                    d += timedelta(days=1)
                attendance_trend.append({
                    'date':    m_start.strftime('%b %Y'),
                    'present': present,
                    'late':    late,
                    'absent':  absent,
                })

        elif period == 'today':
            # 1 query
            today_stats = Attendance.objects.filter(date=now.date()).aggregate(
                present = Count(Case(When(status='present', then=1), output_field=IntegerField())),
                late    = Count(Case(When(status='late',    then=1), output_field=IntegerField())),
                absent  = Count(Case(When(status='absent',  then=1), output_field=IntegerField())),
            )
            attendance_trend.append({
                'date':    now.strftime('%b %d'),
                'present': today_stats['present'],
                'late':    today_stats['late'],
                'absent':  today_stats['absent'],
            })

        else:
            # weekly/monthly — 1 query
            chart_days = days_in_period
            range_start = (now - timedelta(days=chart_days - 1)).date()

            att_qs = (
                Attendance.objects
                .filter(date__gte=range_start, date__lte=now.date())
                .values('date', 'status')
                .annotate(total=Count('id'))
            )
            att_map = {}
            for row in att_qs:
                att_map.setdefault(row['date'], {})[row['status']] = row['total']

            for i in range(chart_days - 1, -1, -1):
                day      = (now - timedelta(days=i)).date()
                day_data = att_map.get(day, {})
                attendance_trend.append({
                    'date':    day.strftime('%b %d'),
                    'present': day_data.get('present', 0),
                    'late':    day_data.get('late',    0),
                    'absent':  day_data.get('absent',  0),
                })

        # ── Task chart ────────────────────────────────────────────
        task_chart = []

        if period == 'yearly':
            # 1 query — all tasks in year grouped by date+status
            task_qs = (
                tasks
                .values('created_at__date', 'status')
                .annotate(total=Count('id'))
            )
            task_map = {}
            for row in task_qs:
                task_map.setdefault(row['created_at__date'], {})[row['status']] = row['total']

            for m_start, m_end in month_ranges:
                approved = completed = pending = 0
                d = m_start.date()
                while d < m_end.date():
                    day_data  = task_map.get(d, {})
                    approved  += day_data.get('approved',  0)
                    completed += day_data.get('completed', 0)
                    pending   += day_data.get('pending',   0)
                    d += timedelta(days=1)
                task_chart.append({
                    'date':      m_start.strftime('%b %Y'),
                    'approved':  approved,
                    'completed': completed,
                    'pending':   pending,
                })

        elif period == 'today':
            # 1 query
            today_task_stats = tasks.aggregate(
                approved  = Count(Case(When(status='approved',  then=1), output_field=IntegerField())),
                completed = Count(Case(When(status='completed', then=1), output_field=IntegerField())),
                pending   = Count(Case(When(status='pending',   then=1), output_field=IntegerField())),
            )
            task_chart.append({
                'date':      now.strftime('%b %d'),
                'approved':  today_task_stats['approved'],
                'completed': today_task_stats['completed'],
                'pending':   today_task_stats['pending'],
            })

        else:
            # weekly/monthly — 1 query
            task_qs = (
                tasks
                .values('created_at__date', 'status')
                .annotate(total=Count('id'))
            )
            task_map = {}
            for row in task_qs:
                task_map.setdefault(row['created_at__date'], {})[row['status']] = row['total']

            for i in range(days_in_period - 1, -1, -1):
                day      = (now - timedelta(days=i)).date()
                day_data = task_map.get(day, {})
                task_chart.append({
                    'date':      day.strftime('%b %d'),
                    'approved':  day_data.get('approved',  0),
                    'completed': day_data.get('completed', 0),
                    'pending':   day_data.get('pending',   0),
                })

        # ── By location ───────────────────────────────────────────
        # FIX: 2 bulk queries instead of N_locations × 4 queries
        locations = Location.objects.filter(status='active')
        loc_ids   = list(locations.values_list('id', flat=True))

        # Bulk task stats per location — 1 query
        loc_task_qs = (
            tasks
            .filter(location_id__in=loc_ids)
            .values('location_id')
            .annotate(
                total     = Count('id'),
                completed = Count(Case(
                    When(status__in=['completed', 'approved'], then=1),
                    output_field=IntegerField()
                )),
            )
        )
        loc_task_map = {row['location_id']: row for row in loc_task_qs}

        # Bulk attendance stats per location — 1 query
        loc_att_qs = (
            Attendance.objects
            .filter(location_id__in=loc_ids, date__gte=start_date.date(), status__in=['present', 'late'])
            .values('location_id')
            .annotate(attended=Count('id'))
        )
        loc_att_map = {row['location_id']: row['attended'] for row in loc_att_qs}

        # Bulk employee count per location — 1 query
        loc_emp_qs = (
            User.objects
            .filter(location_id__in=loc_ids, role__in=EMPLOYEE_ROLES, is_active=True)
            .values('location_id')
            .annotate(emp_count=Count('id'))
        )
        loc_emp_map = {row['location_id']: row['emp_count'] for row in loc_emp_qs}

        task_by_location       = []
        attendance_by_location = []

        for loc in locations:
            task_data = loc_task_map.get(loc.id, {})
            loc_total     = task_data.get('total',     0)
            loc_completed = task_data.get('completed', 0)
            loc_rate      = round((loc_completed / loc_total * 100)) if loc_total > 0 else 0
            task_by_location.append({
                'location_id':     loc.id,
                'location_name':   loc.name,
                'total_tasks':     loc_total,
                'completed':       loc_completed,
                'completion_rate': loc_rate,
            })

            loc_employees = loc_emp_map.get(loc.id, 0)
            loc_attended  = loc_att_map.get(loc.id, 0)
            loc_max       = loc_employees * days_in_period
            loc_att_rate  = round((loc_attended / loc_max * 100)) if loc_max > 0 else 0
            attendance_by_location.append({
                'location_id':     loc.id,
                'location_name':   loc.name,
                'staff_count':     loc_employees,
                'attendance_rate': loc_att_rate,
            })

        task_by_location.sort(key=lambda x: x['completion_rate'], reverse=True)
        attendance_by_location.sort(key=lambda x: x['attendance_rate'], reverse=True)

        # ── Attendance log ────────────────────────────────────────
        if period == 'today':
            days_to_show = [now.date()]
        elif period == 'yearly':
            days_to_show = [(now - timedelta(days=i)).date() for i in range(364, -1, -1)]
        elif period == 'monthly':
            days_to_show = [(now - timedelta(days=i)).date() for i in range(29, -1, -1)]
        else:
            days_to_show = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]

        # 1 query for all days — instead of per-day loop
        att_log_qs = Attendance.objects.filter(date__in=days_to_show)
        if location_filter:
            att_log_qs = att_log_qs.filter(location_id=location_filter)
        if user_filter:
            att_log_qs = att_log_qs.filter(user_id=user_filter)

        att_log_qs = (
            att_log_qs
            .values('date', 'status')
            .annotate(total=Count('id'))
        )
        att_log_map = {}
        for row in att_log_qs:
            att_log_map.setdefault(row['date'], {})[row['status']] = row['total']

        # Resolve location name once — not inside the loop
        loc_name = 'All Locations'
        if location_filter:
            loc_obj  = Location.objects.filter(id=location_filter).first()
            loc_name = loc_obj.name if loc_obj else 'All Locations'

        attendance_by_date = []
        for day in days_to_show:
            day_data      = att_log_map.get(day, {})
            total_present = day_data.get('present', 0)
            total_absent  = day_data.get('absent',  0)
            total_late    = day_data.get('late',    0)
            total         = total_present + total_absent + total_late

            if period == 'yearly' and total == 0:
                continue

            rate  = round((total_present + total_late) / total * 100) if total > 0 else 0
            label = day.strftime('%b %d, %Y')
            if day == now.date():
                label += ' (Today)'

            attendance_by_date.append({
                'date':     label,
                'raw_date': str(day),
                'location': loc_name,
                'present':  total_present,
                'absent':   total_absent,
                'late':     total_late,
                'rate':     f"{rate}%",
            })

        return Response({
            'period': period,
            'stats': {
                'avg_attendance_rate':  avg_attendance,
                'task_completion_rate': completion_rate,
                'total_active_staff':   active_staff,
                'pending_tasks':        pending_tasks,
            },
            'attendance_trend':            attendance_trend,
            'task_completion_chart':       task_chart,
            'attendance_by_location':      attendance_by_location,
            'task_completion_by_location': task_by_location,
            'attendance_log':              attendance_by_date,
        })
# ================================================================
# DASHBOARD
# ================================================================
class DashboardView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        today           = timezone.localdate()
        now             = timezone.now()
        location_filter = request.query_params.get('location')

        # ── Top stats ─────────────────────────────────────────────
        total_employees = User.objects.filter(role__in=EMPLOYEE_ROLES, is_active=True).count()
        total_locations = Location.objects.filter(status='active').count()

        task_stats = Task.objects.aggregate(
            total    = Count('id'),
            pending  = Count(Case(When(status='pending',  then=1), output_field=IntegerField())),
            approved = Count(Case(When(status='approved', then=1), output_field=IntegerField())),
            rejected = Count(Case(When(status='rejected', then=1), output_field=IntegerField())),
        )
        pending_tasks  = task_stats['pending']
        approved_tasks = task_stats['approved']
        rejected_tasks = task_stats['rejected']
        total_count    = task_stats['total']

        checked_in_today = Attendance.objects.filter(date=today).count()
        today_attendance = round((checked_in_today / total_employees * 100)) if total_employees > 0 else 0

        # ── Attendance overview — FIX: 1 query instead of 21 ─────
        overview_start = (now - timedelta(days=6)).date()

        att_overview_qs = (
            Attendance.objects
            .filter(date__gte=overview_start, date__lte=today)
            .values('date', 'status')
            .annotate(total=Count('id'))
        )
        overview_map = {}
        for row in att_overview_qs:
            overview_map.setdefault(row['date'], {})[row['status']] = row['total']

        attendance_overview = []
        for i in range(6, -1, -1):
            day      = (now - timedelta(days=i)).date()
            day_data = overview_map.get(day, {})
            attendance_overview.append({
                'date':    day.strftime('%b %d'),
                'present': day_data.get('present', 0),
                'late':    day_data.get('late',    0),
                'absent':  day_data.get('absent',  0),
            })

        # ── Task status ───────────────────────────────────────────
        task_status = {
            'total':    total_count,
            'pending':  pending_tasks,
            'approved': approved_tasks,
            'rejected': rejected_tasks,
        }

        # ── Task by location — FIX: 1 query instead of N ─────────
        locations = Location.objects.filter(status='active')
        loc_ids   = list(locations.values_list('id', flat=True))

        loc_task_qs = (
            Task.objects
            .filter(location_id__in=loc_ids)
            .values('location_id')
            .annotate(
                pending  = Count(Case(When(status='pending',  then=1), output_field=IntegerField())),
                approved = Count(Case(When(status='approved', then=1), output_field=IntegerField())),
                rejected = Count(Case(When(status='rejected', then=1), output_field=IntegerField())),
            )
        )
        loc_task_map = {row['location_id']: row for row in loc_task_qs}

        task_by_location = []
        for loc in locations:
            loc_data = loc_task_map.get(loc.id, {})
            task_by_location.append({
                'location_id':   loc.id,
                'location_name': loc.name,
                'pending':       loc_data.get('pending',  0),
                'approved':      loc_data.get('approved', 0),
                'rejected':      loc_data.get('rejected', 0),
            })

        # ── Recent activity ───────────────────────────────────────
        recent_logs     = ActivityLog.objects.select_related('actor', 'target_user', 'task')[:10]
        recent_activity = []
        for log in recent_logs:
            recent_activity.append({
                'id':         log.id,
                'action':     log.action,
                'message':    log.message,
                'time_ago':   timesince(log.created_at) + ' ago',
                'created_at': log.created_at,
            })

        # ── Employee breakdown — prefetch keeps this N+1 free ─────
        employees = User.objects.filter(
            role__in  = EMPLOYEE_ROLES,
            is_active = True
        ).select_related('location').prefetch_related(
            Prefetch(
                'attendances',
                queryset=Attendance.objects.filter(date=today),
                to_attr='today_attendances'
            )
        ).order_by('first_name')

        if location_filter:
            employees = employees.filter(location_id=location_filter)

        employee_breakdown = []
        for emp in employees:
            attendance = emp.today_attendances[0] if emp.today_attendances else None
            employee_breakdown.append({
                'id':            emp.id,
                'name':          f"{emp.first_name} {emp.last_name}".strip(),
                'role_display':  emp.get_role_display(),
                'location_name': emp.location.name if emp.location else None,
                'today_status':  attendance.status if attendance else 'absent',
            })

        paginator           = PageNumberPagination()
        paginator.page_size = 5
        paginated_page      = paginator.paginate_queryset(employee_breakdown, request)

        return Response({
            'stats': {
                'total_employees':  total_employees,
                'total_locations':  total_locations,
                'pending_tasks':    pending_tasks,
                'today_attendance': today_attendance,
            },
            'attendance_overview': attendance_overview,
            'task_status':         task_status,
            'task_by_location':    task_by_location,
            'recent_activity':     recent_activity,
            'employee_breakdown':  paginator.get_paginated_response(paginated_page).data,
        })
# ================================================================
# QR HELPERS
# ================================================================

def generate_qr_token():
    return secrets.token_urlsafe(32)


def deactivate_old_qr_sessions(location):
    QRSession.objects.filter(location=location, is_active=True).update(is_active=False)


# ================================================================
# SUPER ADMIN — QR SECTION
# ================================================================

class SuperAdminQRView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        location_filter = request.query_params.get('location')

        active_sessions = QRSession.objects.filter(is_active=True).select_related('location', 'created_by')
        if location_filter:
            active_sessions = active_sessions.filter(location_id=location_filter)

        active_data = []
        for session in active_sessions:
            if session.is_expired:
                session.is_active = False
                session.save(update_fields=['is_active'])
                continue

            # FIX: use aggregate instead of 3 property calls (3 DB hits per session)
            att_stats = Attendance.objects.filter(qr_session=session).aggregate(
                present = Count(Case(When(status='present', then=1), output_field=IntegerField())),
                late    = Count(Case(When(status='late',    then=1), output_field=IntegerField())),
                absent  = Count(Case(When(status='absent',  then=1), output_field=IntegerField())),
            )
            active_data.append({
                "id":               session.id,
                "token":            session.token,
                "location":         session.location.name,
                "location_id":      session.location.id,
                "refresh_interval": session.refresh_interval,
                "interval_display": session.get_refresh_interval_display(),
                "created_at":       session.created_at,
                "expires_at":       session.expires_at,
                "seconds_left":     max(0, int((session.expires_at - timezone.now()).total_seconds())),
                "present_count":    att_stats['present'],
                "late_count":       att_stats['late'],
                "absent_count":     att_stats['absent'],
            })

        history = QRSession.objects.all().annotate(
            present_count=Count('attendances', filter=Q(attendances__status='present')),
            late_count=Count('attendances', filter=Q(attendances__status='late')),
            absent_count=Count('attendances', filter=Q(attendances__status='absent')),
        ).order_by('-created_at')
        if location_filter:
            history = history.filter(location_id=location_filter)

        paginator      = PageNumberPagination()
        page           = paginator.paginate_queryset(history, request)
        serializer     = QRSessionListSerializer(page, many=True)
        paginated_data = paginator.get_paginated_response(serializer.data).data
        locations      = Location.objects.filter(status='active').values('id', 'name')

        return Response({
            "active_sessions": active_data,
            "history":         paginated_data,
            "filter_options":  {"locations": list(locations)},
        }, status=status.HTTP_200_OK)

    def post(self, request):
        location_id = request.data.get('location') or request.data.get('location_id')
        if not location_id:
            return Response({"error": "location is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            location = Location.objects.get(id=location_id, status='active')
        except Location.DoesNotExist:
            return Response({"error": "Location not found."}, status=status.HTTP_404_NOT_FOUND)

        refresh_interval = int(request.data.get('refresh_interval', 3))
        valid_intervals  = [1, 3, 5, 10, 30]
        if refresh_interval not in valid_intervals:
            return Response({"error": f"Invalid interval. Choose from {valid_intervals}"}, status=status.HTTP_400_BAD_REQUEST)

        deactivate_old_qr_sessions(location)

        qr_session = QRSession.objects.create(
            location         = location,
            created_by       = request.user,
            token            = generate_qr_token(),
            refresh_interval = refresh_interval,
            expires_at       = timezone.now() + timedelta(minutes=refresh_interval),
            is_active        = True,
        )

        return Response({
            "message":    "QR session generated successfully.",
            "qr_session": QRSessionSerializer(qr_session).data,
        }, status=status.HTTP_201_CREATED)


class SuperAdminQRDetailView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        qr_session = QRSession.objects.filter(pk=pk).annotate(
            present_count=Count('attendances', filter=Q(attendances__status='present')),
            late_count=Count('attendances', filter=Q(attendances__status='late')),
            absent_count=Count('attendances', filter=Q(attendances__status='absent')),
        ).first()

        if not qr_session:
            return Response({"error": "QR session not found."}, status=status.HTTP_404_NOT_FOUND)

        attendances = Attendance.objects.filter(qr_session=qr_session).select_related('user', 'location')
        return Response({
            "qr_session":  QRSessionSerializer(qr_session).data,
            "attendances": AttendanceSerializer(attendances, many=True).data,
        }, status=status.HTTP_200_OK)


class SuperAdminQRIntervalListView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        intervals = [
            {"value": 1,  "label": "Every 1 minute"},
            {"value": 3,  "label": "Every 3 minutes"},
            {"value": 5,  "label": "Every 5 minutes"},
            {"value": 10, "label": "Every 10 minutes"},
            {"value": 30, "label": "Every 30 minutes"},
        ]
        return Response({"intervals": intervals}, status=status.HTTP_200_OK)


# ================================================================
# CLOCK IN USER — VIEW QR
# ================================================================

class ClockInUserQRView(APIView):
    permission_classes = [IsClockInUser]

    def get(self, request):
        user = request.user
        if not user.location:
            return Response({"error": "You are not assigned to any location."}, status=status.HTTP_400_BAD_REQUEST)

        qr_session = QRSession.objects.filter(location=user.location, is_active=True).first()

        if not qr_session:
            return Response({
                "message": "No active QR session. Please contact admin.",
                "qr_session": None, "location": user.location.name, "seconds_left": 0,
            }, status=status.HTTP_200_OK)

        if qr_session.is_expired:
            qr_session.is_active = False
            qr_session.save(update_fields=['is_active'])
            return Response({
                "message": "QR session has expired. Please contact admin.",
                "qr_session": None, "location": user.location.name, "seconds_left": 0,
            }, status=status.HTTP_200_OK)

        seconds_left = max(0, int((qr_session.expires_at - timezone.now()).total_seconds()))
        return Response({
            "message":  "Active QR session found.",
            "location": user.location.name,
            "user": {
                "id":    user.id,
                "name":  f"{user.first_name} {user.last_name}".strip(),
                "email": user.email,
                "role":  user.get_role_display(),
            },
            "qr_session": {
                "id":               qr_session.id,
                "token":            qr_session.token,
                "refresh_interval": qr_session.refresh_interval,
                "interval_display": qr_session.get_refresh_interval_display(),
                "created_at":       qr_session.created_at,
                "expires_at":       qr_session.expires_at,
            },
            "seconds_left": seconds_left,
        }, status=status.HTTP_200_OK)


# ================================================================
# BRANCH MANAGER VIEWS
# ================================================================

class BranchManagerProfileView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request):
        manager = request.user
        return Response({
            'id':            manager.id,
            'first_name':    manager.first_name,
            'last_name':     manager.last_name,
            'full_name':     manager.get_full_name(),
            'username':      manager.username,
            'email':         manager.email,
            'phone':         manager.phone,
            'role':          manager.role,
            'role_display':  manager.get_role_display(),
            'profile_photo': manager.profile_photo,
            'location': {
                'id':             manager.location.id,
                'name':           manager.location.name,
                'street_address': manager.location.street_address,
                'city_state':     manager.location.city_state,
                'status':         manager.location.status,
            } if manager.location else None,
            'date_joined': manager.date_joined,
            'last_login':  manager.last_login,
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        manager        = request.user
        allowed_fields = ['first_name', 'last_name', 'phone', 'profile_photo']
        for field in allowed_fields:
            if field in request.data:
                setattr(manager, field, request.data[field])
        manager.save()
        return Response({
            'message':       'Profile updated successfully.',
            'id':            manager.id,
            'first_name':    manager.first_name,
            'last_name':     manager.last_name,
            'full_name':     manager.get_full_name(),
            'username':      manager.username,
            'email':         manager.email,
            'phone':         manager.phone,
            'role':          manager.role,
            'role_display':  manager.get_role_display(),
            'profile_photo': manager.profile_photo,
            'location': {
                'id':             manager.location.id,
                'name':           manager.location.name,
                'street_address': manager.location.street_address,
                'city_state':     manager.location.city_state,
                'status':         manager.location.status,
            } if manager.location else None,
        }, status=status.HTTP_200_OK)


class BranchManagerDashboardView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request):
        manager  = request.user
        location = manager.location

        if not location:
            return Response({"error": "You are not assigned to any location."}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        now   = timezone.now()

        hour = now.hour
        if hour < 12:
            greeting_time = "Good morning"
        elif hour < 17:
            greeting_time = "Good afternoon"
        else:
            greeting_time = "Good evening"

        greeting = f"{greeting_time}, {manager.first_name or 'Store Manager'} 👋"

        total_employees       = User.objects.filter(location=location, role__in=EMPLOYEE_ROLES, is_active=True).count()
        pending_verifications = Task.objects.filter(location=location, status='awaiting_review').count()

        # FIX: single aggregate for attendance stats
        att_stats = Attendance.objects.filter(location=location, date=today).aggregate(
            present = Count(Case(When(status='present', then=1), output_field=IntegerField())),
            late    = Count(Case(When(status='late',    then=1), output_field=IntegerField())),
            absent  = Count(Case(When(status='absent',  then=1), output_field=IntegerField())),
        )

        today_attendance = {
            'total':   total_employees,
            'present': att_stats['present'],
            'late':    att_stats['late'],
            'absent':  att_stats['absent'],
        }

        # FIX: prefetch attendance to avoid N+1 in today_staff loop
        employees = User.objects.filter(
            location=location, role__in=EMPLOYEE_ROLES, is_active=True
        ).prefetch_related(
            Prefetch(
                'attendances',
                queryset=Attendance.objects.filter(date=today),
                to_attr='today_attendances'
            )
        )

        today_staff = []
        for emp in employees:
            attendance   = emp.today_attendances[0] if emp.today_attendances else None
            late_minutes = None

            if attendance and attendance.status == 'late' and attendance.clock_in:
                from datetime import time as dt_time
                scheduled = dt_time(9, 0)
                clock_in  = attendance.clock_in
                if clock_in > scheduled:
                    late_minutes = (clock_in.hour * 60 + clock_in.minute) - (scheduled.hour * 60 + scheduled.minute)

            today_staff.append({
                'id':           emp.id,
                'name':         f"{emp.first_name} {emp.last_name}".strip(),
                'role':         emp.get_role_display(),
                'status':       attendance.status if attendance else 'absent',
                'late_minutes': late_minutes,
                'clock_in':     attendance.clock_in.strftime('%I:%M %p') if attendance and attendance.clock_in else None,
            })

        recent_tasks_qs = Task.objects.filter(location=location).select_related('assigned_to').order_by('-created_at')[:5]
        recent_tasks    = []
        status_labels   = {
            'pending': 'Pending', 'completed': 'Completed',
            'awaiting_review': 'Awaiting Review', 'approved': 'Approved',
            'rejected': 'Rejected', 'overdue': 'Overdue',
        }
        for task in recent_tasks_qs:
            recent_tasks.append({
                'id':             task.id,
                'title':          task.title,
                'assigned_to':    f"{task.assigned_to.first_name} {task.assigned_to.last_name}".strip(),
                'due_date':       task.due_date.strftime('%b %d, %Y') if task.due_date else None,
                'status':         task.status,
                'status_display': status_labels.get(task.status, task.status),
            })

        return Response({
            'greeting':      greeting,
            'date_display':  today.strftime('%A, %B %d, %Y'),
            'location_name': location.name,
            'stats': {
                'total_employees':       total_employees,
                'pending_verifications': pending_verifications,
                'today_attendance':      today_attendance,
            },
            'today_staff':  today_staff,
            'recent_tasks': recent_tasks,
        }, status=status.HTTP_200_OK)


class BranchManagerTaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsBranchManager]
    filter_backends    = [SearchFilter]
    search_fields      = ['title', 'description', 'assigned_to__first_name', 'assigned_to__last_name']

    def get_queryset(self):
        manager  = self.request.user
        queryset = Task.objects.filter(location=manager.location).select_related(
            'location', 'assigned_to', 'completed_by', 'approved_by', 'rejected_by', 'created_by'
        ).order_by('-created_at')

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(assigned_to__first_name__icontains=search) |
                Q(assigned_to__last_name__icontains=search)
            )
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return BranchManagerTaskCreateSerializer
        if self.action in ['update', 'partial_update']:
            return TaskUpdateSerializer
        if self.action == 'list':
            return BranchManagerTaskListSerializer
        return TaskDetailSerializer

    def list(self, request, *args, **kwargs):
        manager  = request.user
        queryset = self.filter_queryset(self.get_queryset().filter(status='pending'))

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer     = self.get_serializer(page, many=True)
            paginated_data = self.get_paginated_response(serializer.data)
            return Response({
                'location': manager.location.name if manager.location else None,
                'tasks':    paginated_data.data,
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'location': manager.location.name if manager.location else None,
            'tasks':    serializer.data,
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        manager = request.user
        if not manager.location:
            return Response({"error": "You are not assigned to any location."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        assigned_to = serializer.validated_data.get('assigned_to')
        if assigned_to.location != manager.location:
            return Response({"error": "You can only assign tasks to employees in your location."}, status=status.HTTP_400_BAD_REQUEST)

        task = serializer.save(location=manager.location, created_by=request.user)

        ActivityLog.objects.create(
            action='task_assigned', actor=request.user, task=task,
            target_user=task.assigned_to,
            message=f'Task "{task.title}" assigned to {task.assigned_to.get_full_name()}'
        )

        return Response({
            'message': 'Task created successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        task = self.get_object()
        return Response(TaskDetailSerializer(task).data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        task = self.get_object()
        if task.status != 'pending':
            return Response({"error": "Only pending tasks can be edited."}, status=status.HTTP_400_BAD_REQUEST)
        if task.created_by != request.user:
            return Response({"error": "You can only edit tasks you created."}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response({'message': 'Task updated successfully.', 'task': TaskDetailSerializer(task).data}, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        task = self.get_object()
        if task.status != 'pending':
            return Response({"error": "Only pending tasks can be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        if task.created_by != request.user:
            return Response({"error": "You can only delete tasks you created."}, status=status.HTTP_403_FORBIDDEN)
        task.delete()
        return Response({"message": "Task deleted successfully."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        task = self.get_object()
        if task.status not in ['awaiting_review', 'rejected']:
            return Response({"error": "Only awaiting review or rejected tasks can be approved."}, status=status.HTTP_400_BAD_REQUEST)

        task.status = 'approved'; task.approved_by = request.user; task.approved_at = timezone.now(); task.rejection_reason = None
        task.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason'])
        ActivityLog.objects.create(action='task_approved', actor=request.user, task=task, target_user=task.assigned_to, message=f'Task "{task.title}" approved for {task.assigned_to.get_full_name()}')
        return Response({'message': 'Task approved successfully.', 'task': TaskDetailSerializer(task).data}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        task       = self.get_object()
        serializer = TaskRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if task.status not in ['awaiting_review', 'approved']:
            return Response({"error": "Only awaiting review or approved tasks can be rejected."}, status=status.HTTP_400_BAD_REQUEST)

        task.status = 'rejected'; task.rejected_by = request.user; task.rejected_at = timezone.now(); task.rejection_reason = serializer.validated_data['rejection_reason']
        task.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason'])
        ActivityLog.objects.create(action='task_rejected', actor=request.user, task=task, target_user=task.assigned_to, message=f'Task "{task.title}" rejected — {serializer.validated_data["rejection_reason"]}')
        return Response({'message': 'Task rejected.', 'task': TaskDetailSerializer(task).data}, status=status.HTTP_200_OK)


class BranchManagerLocationEmployeesView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request):
        manager = request.user
        if not manager.location:
            return Response({"error": "You are not assigned to any location."}, status=status.HTTP_400_BAD_REQUEST)

        employees  = User.objects.filter(location=manager.location, role__in=ASSIGNABLE_ROLES, is_active=True)
        serializer = LocationEmployeeSerializer(employees, many=True)
        return Response({
            'location':    manager.location.name,
            'location_id': manager.location.id,
            'employees':   serializer.data,
        }, status=status.HTTP_200_OK)


class BranchManagerVerificationView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request):
        manager = request.user
        if not manager.location:
            return Response({"error": "You are not assigned to any location."}, status=status.HTTP_400_BAD_REQUEST)

        tab = request.query_params.get('tab', 'pending')

        base_tasks = Task.objects.filter(location=manager.location).select_related(
            'location', 'assigned_to', 'approved_by', 'rejected_by', 'created_by'
        )

        # FIX: single aggregate for stats instead of 5 separate counts
        stats_data = base_tasks.aggregate(
            awaiting_review = Count(Case(When(status='awaiting_review', then=1), output_field=IntegerField())),
            approved        = Count(Case(When(status='approved',        then=1), output_field=IntegerField())),
            pending         = Count(Case(When(status='pending',         then=1), output_field=IntegerField())),
            overdue         = Count(Case(When(status='overdue',         then=1), output_field=IntegerField())),
            rejected        = Count(Case(When(status='rejected',        then=1), output_field=IntegerField())),
        )

        TAB_STATUS_MAP  = {'pending': 'pending', 'awaiting_review': 'awaiting_review', 'approved': 'approved', 'rejected': 'rejected', 'overdue': 'overdue'}
        selected_status = TAB_STATUS_MAP.get(tab, 'pending')
        tasks           = base_tasks.filter(status=selected_status).order_by('-created_at')

        paginator = PageNumberPagination()
        page      = paginator.paginate_queryset(tasks, request)

        data = []
        for task in page:
            can_edit = (task.created_by == manager and task.status == 'pending')
            data.append({
                'id':             task.id,
                'title':          task.title,
                'description':    task.description,
                'requires_photo': task.requires_photo,
                'photo_url':      task.photo_url,
                'status':         task.status,
                'due_date':       task.due_date,
                'location_name':  task.location.name if task.location else None,
                'created_by': {
                    'id':   task.created_by.id   if task.created_by else None,
                    'name': f"{task.created_by.first_name} {task.created_by.last_name}".strip() if task.created_by else None,
                    'role': task.created_by.get_role_display() if task.created_by else None,
                },
                'assigned_to': {
                    'id':    task.assigned_to.id,
                    'name':  f"{task.assigned_to.first_name} {task.assigned_to.last_name}".strip(),
                    'role':  task.assigned_to.get_role_display(),
                    'email': task.assigned_to.email,
                },
                'submitted_at':     task.completed_at.strftime('%b %d, %I:%M %p') if task.completed_at else None,
                'created_at':       task.created_at,
                'approved_by':      f"{task.approved_by.first_name} {task.approved_by.last_name}".strip() if task.approved_by else None,
                'approved_at':      task.approved_at,
                'rejected_by':      f"{task.rejected_by.first_name} {task.rejected_by.last_name}".strip() if task.rejected_by else None,
                'rejected_at':      task.rejected_at,
                'rejection_reason': task.rejection_reason,
                'can_edit':         can_edit,
                'can_delete':       can_edit,
            })

        return Response({
            'stats': stats_data,
            'tab':   tab,
            'tasks': paginator.get_paginated_response(data).data,
        }, status=status.HTTP_200_OK)


# ================================================================
# USER ATTENDANCE
# ================================================================

class UserAttendanceView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        from django.db import models as db_models

        period          = request.query_params.get('period', 'weekly')
        location_filter = request.query_params.get('location')
        search          = request.query_params.get('search', '').strip()
        user_id         = request.query_params.get('user')
        now             = timezone.now()

        if period == 'yearly':
            start_date     = now - timedelta(days=365)
            days_in_period = 365
            period_label   = 'year'
        elif period == 'monthly':
            start_date     = now - timedelta(days=30)
            days_in_period = 30
            period_label   = 'month'
        else:
            start_date     = now - timedelta(days=7)
            days_in_period = 7
            period_label   = 'week'

        employees = User.objects.filter(role__in=EMPLOYEE_ROLES, is_active=True).select_related('location').order_by('first_name')

        if location_filter:
            employees = employees.filter(location_id=location_filter)
        if search:
            employees = employees.filter(
                db_models.Q(first_name__icontains=search) |
                db_models.Q(last_name__icontains=search)  |
                db_models.Q(email__icontains=search)
            )
        if user_id:
            employees = employees.filter(id=user_id)

        filter_options = {'locations': list(Location.objects.filter(status='active').values('id', 'name'))}

        if user_id or employees.count() == 1:
            employee = employees.first()
            if not employee:
                return Response({"error": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)
            return self._detail_view(request, employee, start_date, days_in_period, period, period_label, filter_options, now)

        return self._summary_view(request, employees, start_date, days_in_period, period, period_label, filter_options)

    def _summary_view(self, request, employees, start_date, days_in_period, period, period_label, filter_options):
        emp_ids = list(employees.values_list('id', flat=True))

        att_bulk_qs = (
            Attendance.objects
            .filter(user_id__in=emp_ids, date__gte=start_date.date())
            .values('user_id', 'status')
            .annotate(total=Count('id'))
        )
        att_bulk_map = {}
        for row in att_bulk_qs:
            att_bulk_map.setdefault(row['user_id'], {})[row['status']] = row['total']

        summary = []
        for employee in employees:
            emp_data = att_bulk_map.get(employee.id, {})
            summary.append({
                'id':            employee.id,
                'name':          f"{employee.first_name} {employee.last_name}".strip(),
                'role':          employee.get_role_display(),
                'location':      employee.location.name if employee.location else None,
                'location_id':   employee.location.id   if employee.location else None,
                'total_present': emp_data.get('present', 0),
                'total_late':    emp_data.get('late',    0),
                'total_absent':  emp_data.get('absent',  0),
            })

        paginator      = PageNumberPagination()
        page           = paginator.paginate_queryset(summary, request)
        paginated_data = paginator.get_paginated_response(page).data

        return Response({
            'view':         'summary',
            'period':       period,
            'period_label': period_label,
            'employees':    paginated_data,
        }, status=status.HTTP_200_OK)

    def _detail_view(self, request, employee, start_date, days_in_period, period, period_label, filter_options, now):
        records = Attendance.objects.filter(user=employee, date__gte=start_date.date()).order_by('date')

        # FIX: single aggregate for stats
        att_stats = records.aggregate(
            present = Count(Case(When(status='present', then=1), output_field=IntegerField())),
            late    = Count(Case(When(status='late',    then=1), output_field=IntegerField())),
            absent  = Count(Case(When(status='absent',  then=1), output_field=IntegerField())),
        )

        total_weekdays = sum(1 for i in range(days_in_period) if (now - timedelta(days=i)).date().weekday() < 5)
        attendance_map = {r.date: r for r in records}
        daily_log      = []

        for i in range(days_in_period - 1, -1, -1):
            day        = (now - timedelta(days=i)).date()
            record     = attendance_map.get(day)
            is_weekend = day.weekday() >= 5
            day_status = 'weekend' if is_weekend else (record.status if record else 'absent')
            daily_log.append({
                'date':         str(day),
                'date_display': day.strftime('%b %d, %Y'),
                'role':         employee.get_role_display(),
                'status':       day_status,
                'location':     employee.location.name if employee.location else None,
            })

        paginator      = PageNumberPagination()
        page           = paginator.paginate_queryset(daily_log, request)
        paginated_data = paginator.get_paginated_response(page).data

        return Response({
            'view':         'detail',
            'period':       period,
            'period_label': period_label,
            'employee': {
                'id':       employee.id,
                'name':     f"{employee.first_name} {employee.last_name}".strip(),
                'initials': f"{employee.first_name[:1]}{employee.last_name[:1]}".upper(),
                'role':     employee.get_role_display(),
                'location': employee.location.name if employee.location else None,
            },
            'stats': {
                'total_present':  att_stats['present'],
                'total_late':     att_stats['late'],
                'total_absent':   att_stats['absent'],
                'total_weekdays': total_weekdays,
                'period_label':   period_label,
            },
            'attendance_log': paginated_data,
        }, status=status.HTTP_200_OK)


# ================================================================
# NOTIFICATION VIEWSET
# ================================================================

class NotificationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    http_method_names  = ['get', 'post', 'delete']

    def get_queryset(self):
        return Notification.objects.select_related('sent_by', 'recipient', 'location').order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return NotificationCreateSerializer
        return NotificationSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # FIX: single aggregate for stats
        stats_data = queryset.aggregate(
            total_sent = Count('id'),
            delivered  = Count(Case(When(status='sent', then=1), output_field=IntegerField())),
        )
        stats = NotificationStatsSerializer({
            'total_sent':       stats_data['total_sent'],
            'delivered':        stats_data['delivered'],
            'active_locations': Location.objects.filter(status='active').count(),
        }).data

        recent     = queryset[:10]
        serializer = NotificationSerializer(recent, many=True)
        return Response({
            'stats':                stats,
            'recent_notifications': serializer.data,
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = NotificationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email    = serializer.validated_data.get('email')
        location = serializer.validated_data.get('location')
        message  = serializer.validated_data['message']

        if email:
            try:
                recipients = [User.objects.get(email=email, is_active=True)]
            except User.DoesNotExist:
                return Response({"error": "No active user found with this email."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            recipients = list(User.objects.filter(is_active=True).exclude(role='super_admin'))

        sent_count   = 0
        failed_count = 0

        for recipient in recipients:
            notification_status = 'sent'
            try:
                send_mail(
                    subject        = "Salvation Tattoo Lounge — Notification",
                    message        = message,
                    from_email     = settings.DEFAULT_FROM_EMAIL,
                    recipient_list = [recipient.email],
                    fail_silently  = False,
                )
                sent_count += 1
            except Exception as e:
                print(f"Notification email failed for {recipient.email}: {e}")
                notification_status = 'failed'
                failed_count += 1

            Notification.objects.create(
                sent_by   = request.user,
                recipient = recipient,
                email     = recipient.email,
                location  = location or recipient.location,
                message   = message,
                status    = notification_status,
            )

        return Response({
            'message':      f'Notification sent to {sent_count} user(s). {failed_count} failed.',
            'sent_count':   sent_count,
            'failed_count': failed_count,
            'total':        sent_count + failed_count,
        }, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        notification = self.get_object()
        notification.delete()
        return Response({"message": "Notification deleted."}, status=status.HTTP_200_OK)