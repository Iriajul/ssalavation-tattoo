# apps/admin_api/views.py
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken

from .models import Location, UserWorkSchedule, Task, Instruction
from .permissions import IsSuperAdmin
from .serializers import (
    # Auth
    CustomTokenObtainPairSerializer,
    ForgotPasswordSerializer,
    VerifyResetOTPSerializer,
    ResetPasswordSerializer,
    # Location
    LocationSerializer,
    LocationListSerializer,
    LocationStatsSerializer,
    # User
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    UserStatsSerializer,
    # Task
    TaskListSerializer,
    TaskDetailSerializer,
    TaskCreateSerializer,
    TaskUpdateSerializer,
    TaskRejectSerializer,
    TaskStatsSerializer,
    LocationEmployeeSerializer,
    # Instruction
    InstructionSerializer,
    InstructionListSerializer,
    InstructionStatsSerializer,
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
                subject="Salvation Tattoo Admin Password Reset Code",
                message=f"Your 5-digit reset code is: {otp}\n\nThis code will expire in 10 minutes.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
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
        queryset         = self.get_queryset()
        total_locations  = queryset.count()
        active_locations = queryset.filter(status='active').count()
        total_staff      = User.objects.filter(is_active=True, location__isnull=False).count()

        stats      = LocationStatsSerializer({
            'total_locations':  total_locations,
            'total_staff':      total_staff,
            'active_locations': active_locations,
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
        all_users = User.objects.exclude(role='super_admin')

        stats = UserStatsSerializer({
            'district_managers': all_users.filter(role='district_manager').count(),
            'managers':          all_users.filter(role='branch_manager').count(),
            'employees':         all_users.filter(role__in=EMPLOYEE_ROLES).count(),
        }).data

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
        user = User.objects.prefetch_related('work_schedules').get(pk=user.pk)
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


# ================================================================
# TASK VIEWSET
# ================================================================

class TaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    filter_backends    = [SearchFilter]
    search_fields      = ['title', 'description', 'assigned_to__first_name', 'assigned_to__last_name']

    def get_queryset(self):
        queryset = Task.objects.select_related(
            'location', 'assigned_to', 'completed_by',
            'approved_by', 'rejected_by', 'created_by'
        ).order_by('-created_at')

        status_filter   = self.request.query_params.get('status')
        location_filter = self.request.query_params.get('location')

        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if location_filter:
            queryset = queryset.filter(location_id=location_filter)

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
        queryset  = self.filter_queryset(self.get_queryset())
        all_tasks = Task.objects.all()

        stats = TaskStatsSerializer({
            'all_tasks': all_tasks.count(),
            'pending':   all_tasks.filter(status='pending').count(),
            'completed': all_tasks.filter(status='completed').count(),
            'approved':  all_tasks.filter(status='approved').count(),
        }).data

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated  = self.get_paginated_response(serializer.data)
            return Response({
                'stats': stats,
                'tasks': paginated.data,
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'stats': stats,
            'tasks': serializer.data,
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(created_by=request.user)
        return Response({
            'message': 'Task created successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        task = self.get_object()
        return Response(TaskDetailSerializer(task).data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        task       = self.get_object()
        serializer = self.get_serializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response({
            'message': 'Task updated successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        task = self.get_object()
        task.delete()
        return Response(
            {"message": "Task deleted successfully."},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        task = self.get_object()

        if task.status not in ['completed', 'rejected']:
            return Response(
                {"error": "Only completed or previously rejected tasks can be approved."},
                status=status.HTTP_400_BAD_REQUEST
            )

        task.status           = 'approved'
        task.approved_by      = request.user
        task.approved_at      = timezone.now()
        task.rejection_reason = None
        task.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason'])

        return Response({
            'message': 'Task approved successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        task       = self.get_object()
        serializer = TaskRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if task.status not in ['completed', 'approved']:
            return Response(
                {"error": "Only completed or approved tasks can be rejected."},
                status=status.HTTP_400_BAD_REQUEST
            )

        task.status           = 'rejected'
        task.rejected_by      = request.user
        task.rejected_at      = timezone.now()
        task.rejection_reason = serializer.validated_data['rejection_reason']
        task.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason'])

        return Response({
            'message': 'Task rejected.',
            'task':    TaskDetailSerializer(task).data,
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
            location=location,
            role__in=ASSIGNABLE_ROLES,
            is_active=True
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
        if role_filter:
            queryset = queryset.filter(role_visibility__contains=role_filter)
        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return InstructionListSerializer
        return InstructionSerializer


    def list(self, request, *args, **kwargs):
        queryset     = self.filter_queryset(self.get_queryset())
        all_instruct = Instruction.objects.all()

        # ── Stats ────────────────────────────────────────────────
        stats = InstructionStatsSerializer({
            'total_instructions': all_instruct.count(),
            'tattoo_artists':     all_instruct.filter(role_visibility__contains='tattoo_artist').count(),
            'body_piercers':      all_instruct.filter(role_visibility__contains='body_piercer').count(),
            'staff':              all_instruct.filter(role_visibility__contains='staff').count(),
        }).data

        # ── Group by role for frontend sections ──────────────────
        serializer = self.get_serializer(queryset, many=True)
        all_data   = serializer.data

        grouped = {
            'tattoo_artist': [i for i in all_data if 'tattoo_artist' in i['role_visibility']],
            'body_piercer':  [i for i in all_data if 'body_piercer'  in i['role_visibility']],
            'staff':         [i for i in all_data if 'staff'         in i['role_visibility']],
        }

        return Response({
            'stats':        stats,
            'instructions': all_data,
            'grouped':      grouped,
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = InstructionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instruction = serializer.save(created_by=request.user)

        return Response({
            'message': 'Instruction created successfully.',
            'instruction': InstructionSerializer(instruction).data,
        }, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instruction = self.get_object()

        serializer = InstructionSerializer(
            instruction,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        instruction = serializer.save()

        return Response({
            'message': 'Instruction updated successfully.',
            'instruction': InstructionSerializer(instruction).data,
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instruction = self.get_object()
        instruction.delete()
        return Response(
            {"message": "Instruction deleted successfully."},
            status=status.HTTP_200_OK
        )