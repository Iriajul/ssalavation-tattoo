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
import secrets
from django.db.models import Prefetch
from .models import FAQ, Attendance, Location, QRSession, SplashScreen, UserWorkSchedule, Task, Instruction, ActivityLog
from .permissions import IsBranchManager, IsSuperAdmin
from .serializers import (
    AdminChangePasswordSerializer,
    AdminProfileSerializer,
    AttendanceSerializer,
    BranchManagerTaskCreateSerializer,
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
    LocationEmployeeSerializer,
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

        # ── Re-fetch with only the sent days to avoid stale cache ─
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

    # ── Suspend ───────────────────────────────────────────────────
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

    # ── Activate ──────────────────────────────────────────────────
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
        if role_filter and role_filter != 'all':
            queryset = queryset.filter(role_visibility__contains=role_filter)
        return queryset
 
    def get_serializer_class(self):
        if self.action == 'list':
            return InstructionListSerializer
        return InstructionSerializer
 
    def _parse_role_visibility(self, request):
        """
        Handles role_visibility from:
        - form-data multiple keys: role_visibility=tattoo_artist & role_visibility=staff
        - form-data JSON string:   role_visibility=["tattoo_artist","staff"]
        - JSON body:               role_visibility: ["tattoo_artist","staff"]
        """
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

        # ── Stats (always from all instructions) ─────────────────
        stats = InstructionStatsSerializer({
            'total_instructions': all_instruct.count(),
            'tattoo_artists':     all_instruct.filter(role_visibility__contains='tattoo_artist').count(),
            'body_piercers':      all_instruct.filter(role_visibility__contains='body_piercer').count(),
            'staff':              all_instruct.filter(role_visibility__contains='staff').count(),
            'branch_managers':    all_instruct.filter(role_visibility__contains='branch_manager').count(),
            'district_managers':  all_instruct.filter(role_visibility__contains='district_manager').count(),
        }).data

        serializer = self.get_serializer(queryset, many=True)
        all_data   = serializer.data

        # ── If role filter applied — return flat filtered list ────
        if role_filter and role_filter != 'all':
            return Response({
                'stats':        stats,
                'instructions': all_data,
            }, status=status.HTTP_200_OK)

        # ── Default — return grouped by section ───────────────────
        employee_instructions = [
            i for i in all_data
            if any(r in i['role_visibility'] for r in ['tattoo_artist', 'body_piercer', 'staff'])
        ]
        manager_instructions = [
            i for i in all_data
            if 'branch_manager' in i['role_visibility']
        ]
        district_manager_instructions = [
            i for i in all_data
            if 'district_manager' in i['role_visibility']
        ]

        grouped = [
            {
                'section':        'Employees Instructions',
                'document_count': len(employee_instructions),
                'instructions':   employee_instructions,
            },
            {
                'section':        'Managers Instructions',
                'document_count': len(manager_instructions),
                'instructions':   manager_instructions,
            },
            {
                'section':        'District Managers Instructions',
                'document_count': len(district_manager_instructions),
                'instructions':   district_manager_instructions,
            },
        ]

        return Response({
            'stats':  stats,
            'grouped': grouped,
        }, status=status.HTTP_200_OK)
 
    def create(self, request, *args, **kwargs):
        data                   = request.data.copy()
        data['role_visibility'] = self._parse_role_visibility(request)
 
        serializer = InstructionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        instruction = serializer.save(created_by=request.user)
 
        return Response({
            'message':     'Instruction created successfully.',
            'instruction': InstructionSerializer(instruction).data,
        }, status=status.HTTP_201_CREATED)
 
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

    # ↓ REPLACE THIS METHOD
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
        return Response(SplashScreenSerializer(obj).data if obj else {"image_url": None})

    def post(self, request):
        image = request.FILES.get('image')
        if not image:
            return Response({"error": "No image provided."}, status=400)

        import cloudinary.uploader
        result = cloudinary.uploader.upload(image, folder="splash_screen")

        obj, _ = SplashScreen.objects.get_or_create(id=1)
        obj.image_url = result['secure_url']
        obj.save()

        return Response({
            "message":   "Splash screen updated.",
            "image_url": obj.image_url,
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

        return Response({
            "message": "Password updated successfully. Please login again."
        })


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
        period = request.query_params.get('period', 'weekly')

        now = timezone.now()
        if period == 'monthly':
            start_date     = now - timedelta(days=30)
            days_in_period = 30
        else:
            start_date     = now - timedelta(days=7)
            days_in_period = 7

        employees = User.objects.filter(
            role__in=EMPLOYEE_ROLES,
            is_active=True
        )

        tasks_in_period = Task.objects.filter(
            assigned_to__role__in=EMPLOYEE_ROLES,
        )

        # ── Per-employee stats ────────────────────────────────────
        rankings = []
        for employee in employees:
            emp_tasks         = tasks_in_period.filter(assigned_to=employee)
            total             = emp_tasks.count()
            completed         = emp_tasks.filter(status__in=['completed', 'approved']).count()
            overdue           = emp_tasks.filter(status='overdue').count()
            completion_rate   = round((completed / total * 100)) if total > 0 else 0
            overdue_penalty   = (overdue / total * 100) if total > 0 else 0
            performance_score = round((completion_rate * 0.7) + ((100 - overdue_penalty) * 0.3))

            # ── Per-employee attendance ───────────────────────────
            emp_attended   = Attendance.objects.filter(
                user       = employee,
                date__gte  = start_date.date(),
                status__in = ['present', 'late']
            ).count()
            emp_attendance = round((emp_attended / days_in_period * 100)) if days_in_period > 0 else 0

            rankings.append({
                'user':               employee,
                'tasks_completed':    completed,
                'total_tasks':        total,
                'overdue':            overdue,
                'completion_rate':    completion_rate,
                'performance_score':  performance_score,
                'attendance':         emp_attendance,
                'status':             get_performance_status(completion_rate),
            })

        rankings.sort(key=lambda x: x['performance_score'], reverse=True)

        # ── Top performer ─────────────────────────────────────────
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

        # ── Avg attendance rate ───────────────────────────────────
        total_emp      = employees.count()
        total_attended = Attendance.objects.filter(
            user__in   = employees,
            date__gte  = start_date.date(),
            status__in = ['present', 'late']
        ).count()
        max_possible     = total_emp * days_in_period
        avg_attendance   = round((total_attended / max_possible * 100)) if max_possible > 0 else 0

        # ── Build ranked list ─────────────────────────────────────
        ranked_list = []
        for i, r in enumerate(rankings, start=1):
            ranked_list.append({
                'rank':               i,
                'id':                 r['user'].id,
                'name':               f"{r['user'].first_name} {r['user'].last_name}".strip(),
                'email':              r['user'].email,
                'tasks_completed':    r['tasks_completed'],
                'overdue':            r['overdue'],
                'completion_rate':    r['completion_rate'],
                'performance_score':  r['performance_score'],
                'attendance':         r['attendance'],
                'status':             r['status'],
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
                'active_employees':      employees.count(),
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
        period          = request.query_params.get('period', 'weekly')
        location_filter = request.query_params.get('location')
        user_filter     = request.query_params.get('user')

        now = timezone.now()
        if period == 'monthly':
            start_date     = now - timedelta(days=30)
            days_in_period = 30
        else:
            start_date     = now - timedelta(days=7)
            days_in_period = 7

        # ── Tasks ─────────────────────────────────────────────────
        tasks = Task.objects.filter(created_at__gte=start_date)
        if location_filter:
            tasks = tasks.filter(location_id=location_filter)
        if user_filter:
            tasks = tasks.filter(assigned_to_id=user_filter)

        total_tasks     = tasks.count()
        completed_tasks = tasks.filter(status__in=['completed', 'approved']).count()
        pending_tasks   = tasks.filter(status='pending').count()
        completion_rate = round((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0
        active_staff    = User.objects.filter(role__in=EMPLOYEE_ROLES, is_active=True).count()

        # ── Avg attendance rate ───────────────────────────────────
        total_employees = User.objects.filter(role__in=EMPLOYEE_ROLES, is_active=True).count()
        total_attended  = Attendance.objects.filter(
            date__gte  = start_date.date(),
            status__in = ['present', 'late']
        ).count()
        max_possible    = total_employees * days_in_period
        avg_attendance  = round((total_attended / max_possible * 100)) if max_possible > 0 else 0

        # ── Attendance trend chart ────────────────────────────────
        attendance_trend = []
        for i in range(6, -1, -1):
            day         = (now - timedelta(days=i)).date()
            day_records = Attendance.objects.filter(date=day)
            attendance_trend.append({
                'date':    day.strftime('%b %d'),
                'present': day_records.filter(status='present').count(),
                'late':    day_records.filter(status='late').count(),
                'absent':  day_records.filter(status='absent').count(),
            })

        # ── Weekly task completion chart ──────────────────────────
        weekly_chart = []
        for i in range(6, -1, -1):
            day       = (now - timedelta(days=i)).date()
            day_tasks = tasks.filter(created_at__date=day)
            weekly_chart.append({
                'date':      day.strftime('%b %d'),
                'approved':  day_tasks.filter(status='approved').count(),
                'completed': day_tasks.filter(status='completed').count(),
                'pending':   day_tasks.filter(status='pending').count(),
            })

        # ── By location ───────────────────────────────────────────
        locations              = Location.objects.filter(status='active')
        task_by_location       = []
        attendance_by_location = []

        for loc in locations:
            # Task completion by location
            loc_tasks     = tasks.filter(location=loc)
            loc_total     = loc_tasks.count()
            loc_completed = loc_tasks.filter(status__in=['completed', 'approved']).count()
            loc_rate      = round((loc_completed / loc_total * 100)) if loc_total > 0 else 0
            task_by_location.append({
                'location_id':     loc.id,
                'location_name':   loc.name,
                'total_tasks':     loc_total,
                'completed':       loc_completed,
                'completion_rate': loc_rate,
            })

            # Attendance by location
            loc_employees   = User.objects.filter(
                location   = loc,
                role__in   = EMPLOYEE_ROLES,
                is_active  = True
            ).count()
            loc_attended    = Attendance.objects.filter(
                location   = loc,
                date__gte  = start_date.date(),
                status__in = ['present', 'late']
            ).count()
            loc_max         = loc_employees * days_in_period
            loc_att_rate    = round((loc_attended / loc_max * 100)) if loc_max > 0 else 0
            attendance_by_location.append({
                'location_id':     loc.id,
                'location_name':   loc.name,
                'staff_count':     loc_employees,
                'attendance_rate': loc_att_rate,
            })

        task_by_location.sort(key=lambda x: x['completion_rate'], reverse=True)
        attendance_by_location.sort(key=lambda x: x['attendance_rate'], reverse=True)

        # ── Attendance log — grouped by date ─────────────────────────
        from django.db.models import Count, Q

        attendance_by_date = []

        # Get last 7 days
        for i in range(6, -1, -1):
            day = (now - timedelta(days=i)).date()

            day_records = Attendance.objects.filter(date=day)
            if location_filter:
                day_records = day_records.filter(location_id=location_filter)
            if user_filter:
                day_records = day_records.filter(user_id=user_filter)

            total_present = day_records.filter(status='present').count()
            total_absent  = day_records.filter(status='absent').count()
            total_late    = day_records.filter(status='late').count()
            total         = total_present + total_absent + total_late

            rate = round((total_present + total_late) / total * 100) if total > 0 else 0

            # Label today
            label = day.strftime('%b %d, %Y')
            if day == now.date():
                label += ' (Today)'

            attendance_by_date.append({
                'date':     label,
                'raw_date': str(day),
                'location': 'All Locations' if not location_filter else Location.objects.filter(id=location_filter).first().name if Location.objects.filter(id=location_filter).exists() else 'All Locations',
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
            'weekly_task_completion':      weekly_chart,
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

        # ── Stat cards ────────────────────────────────────────────
        total_employees = User.objects.filter(
            role__in=EMPLOYEE_ROLES, is_active=True
        ).count()
        total_locations = Location.objects.filter(status='active').count()
        all_tasks       = Task.objects.all()
        pending_tasks   = all_tasks.filter(status='pending').count()
        approved_tasks  = all_tasks.filter(status='approved').count()
        rejected_tasks  = all_tasks.filter(status='rejected').count()
        total_count     = all_tasks.count()

        # ── Today's attendance % ──────────────────────────────────
        checked_in_today = Attendance.objects.filter(date=today).count()
        today_attendance = round((checked_in_today / total_employees * 100)) if total_employees > 0 else 0

        # ── Attendance overview — last 7 days ─────────────────────
        attendance_overview = []
        for i in range(6, -1, -1):
            day         = (now - timedelta(days=i)).date()
            day_records = Attendance.objects.filter(date=day)
            attendance_overview.append({
                'date':    day.strftime('%b %d'),
                'present': day_records.filter(status='present').count(),
                'late':    day_records.filter(status='late').count(),
                'absent':  day_records.filter(status='absent').count(),
            })

        # ── Task status ───────────────────────────────────────────
        task_status = {
            'total':    total_count,
            'pending':  pending_tasks,
            'approved': approved_tasks,
            'rejected': rejected_tasks,
        }

        # ── Task status by location ───────────────────────────────
        locations        = Location.objects.filter(status='active')
        task_by_location = []
        for loc in locations:
            loc_tasks = all_tasks.filter(location=loc)
            task_by_location.append({
                'location_id':   loc.id,
                'location_name': loc.name,
                'pending':       loc_tasks.filter(status='pending').count(),
                'approved':      loc_tasks.filter(status='approved').count(),
                'rejected':      loc_tasks.filter(status='rejected').count(),
            })

        # ── Recent activity ───────────────────────────────────────
        recent_logs     = ActivityLog.objects.select_related(
            'actor', 'target_user', 'task'
        )[:10]
        recent_activity = []
        for log in recent_logs:
            recent_activity.append({
                'id':         log.id,
                'action':     log.action,
                'message':    log.message,
                'time_ago':   timesince(log.created_at) + ' ago',
                'created_at': log.created_at,
            })

        # ── Today's employee breakdown (paginated) ────────────────
        employees = User.objects.filter(
            role__in=EMPLOYEE_ROLES,
            is_active=True
        ).select_related('location').order_by('first_name')

        if location_filter:
            employees = employees.filter(location_id=location_filter)

        employee_breakdown = []
        for emp in employees:
            attendance = Attendance.objects.filter(
                user=emp,
                date=today
            ).first()

            employee_breakdown.append({
                'id':            emp.id,
                'name':          f"{emp.first_name} {emp.last_name}".strip(),
                'role_display':  emp.get_role_display(),
                'location_name': emp.location.name if emp.location else None,
                'today_status':  attendance.status if attendance else 'absent',
            })

        # Apply pagination to the list
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
            'attendance_overview':  attendance_overview,
            'task_status':          task_status,
            'task_by_location':     task_by_location,
            'recent_activity':      recent_activity,
            'employee_breakdown':   paginator.get_paginated_response(paginated_page).data,  # ← fix
        })

# ================================================================
# BRANCH MANAGER — QR ATTENDANCE
# ================================================================

def generate_qr_token():
    return secrets.token_urlsafe(32)


def deactivate_old_qr_sessions(location):
    QRSession.objects.filter(
        location=location,
        is_active=True
    ).update(is_active=False)


class QRGenerateView(APIView):
    permission_classes = [IsBranchManager]

    def post(self, request):
        manager = request.user

        if not manager.location:
            return Response(
                {"error": "You are not assigned to any location."},
                status=status.HTTP_400_BAD_REQUEST
            )

        refresh_interval = int(request.data.get('refresh_interval', 3))
        valid_intervals  = [1, 3, 5, 10, 30]

        if refresh_interval not in valid_intervals:
            return Response(
                {"error": f"Invalid interval. Choose from {valid_intervals}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        deactivate_old_qr_sessions(manager.location)

        qr_session = QRSession.objects.create(
            location         = manager.location,
            created_by       = manager,
            token            = generate_qr_token(),
            refresh_interval = refresh_interval,
            expires_at       = timezone.now() + timedelta(minutes=refresh_interval),
            is_active        = True,
        )

        return Response({
            "message":    "QR session generated successfully.",
            "qr_session": QRSessionSerializer(qr_session).data,
        }, status=status.HTTP_201_CREATED)


class QRCurrentView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request):
        manager = request.user

        if not manager.location:
            return Response(
                {"error": "You are not assigned to any location."},
                status=status.HTTP_400_BAD_REQUEST
            )

        qr_session = QRSession.objects.filter(
            location=manager.location,
            is_active=True
        ).first()

        if not qr_session:
            return Response(
                {"message": "No active QR session. Please generate one."},
                status=status.HTTP_404_NOT_FOUND
            )

        if qr_session.is_expired:
            qr_session.is_active = False
            qr_session.save(update_fields=['is_active'])
            return Response(
                {"message": "QR session has expired. Please regenerate."},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            "qr_session":   QRSessionSerializer(qr_session).data,
            "seconds_left": max(
                0,
                int((qr_session.expires_at - timezone.now()).total_seconds())
            ),
        }, status=status.HTTP_200_OK)


class QRHistoryView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request):
        manager = request.user

        if not manager.location:
            return Response(
                {"error": "You are not assigned to any location."},
                status=status.HTTP_400_BAD_REQUEST
            )

        sessions       = QRSession.objects.filter(
            location=manager.location
        ).order_by('-created_at')

        paginator      = PageNumberPagination()
        page           = paginator.paginate_queryset(sessions, request)
        serializer     = QRSessionListSerializer(page, many=True)
        paginated_data = paginator.get_paginated_response(serializer.data).data

        return Response({
            "location": manager.location.name,
            "history":  paginated_data,
        }, status=status.HTTP_200_OK)


class QRSessionDetailView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request, pk):
        manager = request.user

        try:
            qr_session = QRSession.objects.get(
                pk=pk,
                location=manager.location
            )
        except QRSession.DoesNotExist:
            return Response(
                {"error": "QR session not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        attendances = Attendance.objects.filter(
            qr_session=qr_session
        ).select_related('user', 'location')

        return Response({
            "qr_session":  QRSessionSerializer(qr_session).data,
            "attendances": AttendanceSerializer(attendances, many=True).data,
        }, status=status.HTTP_200_OK)


class QRIntervalListView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request):
        intervals = [
            {"value": 1,  "label": "Every 1 minute"},
            {"value": 3,  "label": "Every 3 minutes"},
            {"value": 5,  "label": "Every 5 minutes"},
            {"value": 10, "label": "Every 10 minutes"},
            {"value": 30, "label": "Every 30 minutes"},
        ]
        return Response({"intervals": intervals}, status=status.HTTP_200_OK)
    


class BranchManagerTaskViewSet(viewsets.ModelViewSet):
    permission_classes = [IsBranchManager]
    filter_backends    = [SearchFilter]
    search_fields      = ['title', 'description', 'assigned_to__first_name', 'assigned_to__last_name']

    def get_queryset(self):
        manager  = self.request.user

        # ── Only tasks for manager's location ─────────────────────
        queryset = Task.objects.filter(
            location=manager.location
        ).select_related(
            'location', 'assigned_to', 'completed_by',
            'approved_by', 'rejected_by', 'created_by'
        ).order_by('-created_at')

        # ── Status filter ─────────────────────────────────────────
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return BranchManagerTaskCreateSerializer
        if self.action in ['update', 'partial_update']:
            return TaskUpdateSerializer
        if self.action == 'list':
            return TaskListSerializer
        return TaskDetailSerializer

    def list(self, request, *args, **kwargs):
        manager  = request.user
        queryset = self.filter_queryset(self.get_queryset())

        # ── Stats for this location only ──────────────────────────
        location_tasks = Task.objects.filter(location=manager.location)
        stats = {
            'all':            location_tasks.count(),
            'pending':        location_tasks.filter(status='pending').count(),
            'awaiting_review': location_tasks.filter(status='completed').count(),
            'approved':       location_tasks.filter(status='approved').count(),
            'overdue':        location_tasks.filter(status='overdue').count(),
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer     = self.get_serializer(page, many=True)
            paginated_data = self.get_paginated_response(serializer.data)
            return Response({
                'location': manager.location.name if manager.location else None,
                'stats':    stats,
                'tasks':    paginated_data.data,
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'location': manager.location.name if manager.location else None,
            'stats':    stats,
            'tasks':    serializer.data,
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        manager = request.user

        if not manager.location:
            return Response(
                {"error": "You are not assigned to any location."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # ── Validate employee belongs to manager's location ───────
        assigned_to = serializer.validated_data.get('assigned_to')
        if assigned_to.location != manager.location:
            return Response(
                {"error": "You can only assign tasks to employees in your location."},
                status=status.HTTP_400_BAD_REQUEST
            )

        task = serializer.save(
            location   = manager.location,
            created_by = request.user,
        )

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


class BranchManagerLocationEmployeesView(APIView):
    """Get employees for manager's location — for assign dropdown"""
    permission_classes = [IsBranchManager]

    def get(self, request):
        manager = request.user

        if not manager.location:
            return Response(
                {"error": "You are not assigned to any location."},
                status=status.HTTP_400_BAD_REQUEST
            )

        employees = User.objects.filter(
            location  = manager.location,
            role__in  = ASSIGNABLE_ROLES,
            is_active = True
        )

        serializer = LocationEmployeeSerializer(employees, many=True)
        return Response({
            'location':  manager.location.name,
            'location_id': manager.location.id,
            'employees': serializer.data,
        }, status=status.HTTP_200_OK)



class BranchManagerVerificationView(APIView):
    permission_classes = [IsBranchManager]

    def get(self, request):
        manager = request.user

        if not manager.location:
            return Response(
                {"error": "You are not assigned to any location."},
                status=status.HTTP_400_BAD_REQUEST
            )

        tab = request.query_params.get('tab', 'pending')

        # ── Base queryset — only this location's tasks ─────────────
        base_tasks = Task.objects.filter(
            location=manager.location
        ).select_related('assigned_to', 'approved_by', 'rejected_by')

        # ── Stats ──────────────────────────────────────────────────
        stats = {
            'awaiting_review': base_tasks.filter(status='completed').count(),
            'approved':        base_tasks.filter(status='approved').count(),
            'rejected':        base_tasks.filter(status='rejected').count(),
        }

        # ── Tab filter ─────────────────────────────────────────────
        if tab == 'resolved':
            tasks = base_tasks.filter(status__in=['approved', 'rejected'])
        else:
            # pending tab = awaiting review = completed by employee
            tasks = base_tasks.filter(status='completed')

        tasks = tasks.order_by('-completed_at')

        # ── Paginate ───────────────────────────────────────────────
        paginator  = PageNumberPagination()
        page       = paginator.paginate_queryset(tasks, request)

        data = []
        for task in page:
            data.append({
                'id':             task.id,
                'title':          task.title,
                'description':    task.description,
                'requires_photo': task.requires_photo,
                'photo_url':      task.photo_url,
                'status':         task.status,
                'assigned_to': {
                    'id':    task.assigned_to.id,
                    'name':  f"{task.assigned_to.first_name} {task.assigned_to.last_name}".strip(),
                    'email': task.assigned_to.email,
                },
                'completed_at':      task.completed_at,
                'approved_by': f"{task.approved_by.first_name} {task.approved_by.last_name}".strip() if task.approved_by else None,
                'approved_at':       task.approved_at,
                'rejected_by': f"{task.rejected_by.first_name} {task.rejected_by.last_name}".strip() if task.rejected_by else None,
                'rejected_at':       task.rejected_at,
                'rejection_reason':  task.rejection_reason,
            })

        return Response({
            'stats':   stats,
            'tab':     tab,
            'tasks':   paginator.get_paginated_response(data).data,
        }, status=status.HTTP_200_OK)
    


class UserAttendanceView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        from django.db import models as db_models

        period          = request.query_params.get('period', 'weekly')
        location_filter = request.query_params.get('location')
        search          = request.query_params.get('search', '').strip()
        user_id         = request.query_params.get('user')

        # ── Date range ────────────────────────────────────────────
        now = timezone.now()
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

        # ── Base employee queryset ────────────────────────────────
        employees = User.objects.filter(
            role__in  = EMPLOYEE_ROLES,
            is_active = True
        ).select_related('location').order_by('first_name')

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

        # ── Filter options for dropdowns ──────────────────────────
        filter_options = {
            'locations': list(
                Location.objects.filter(status='active').values('id', 'name')
            )
        }

        # ── Drill-down: single employee ───────────────────────────
        if user_id or employees.count() == 1:
            employee = employees.first()
            if not employee:
                return Response(
                    {"error": "Employee not found."},
                    status=status.HTTP_404_NOT_FOUND
                )
            return self._detail_view(
                request, employee, start_date,
                days_in_period, period, period_label,
                filter_options, now
            )

        # ── Default: summary table ────────────────────────────────
        return self._summary_view(
            request, employees, start_date,
            days_in_period, period, period_label,
            filter_options
        )

    # ================================================================
    # SUMMARY VIEW — all employees aggregated
    # ================================================================
    def _summary_view(self, request, employees, start_date, days_in_period, period, period_label, filter_options):
        summary = []

        for employee in employees:
            records       = Attendance.objects.filter(
                user      = employee,
                date__gte = start_date.date()
            )
            total_present = records.filter(status='present').count()
            total_late    = records.filter(status='late').count()
            total_absent  = records.filter(status='absent').count()

            summary.append({
                'id':            employee.id,
                'name':          f"{employee.first_name} {employee.last_name}".strip(),
                'role':          employee.get_role_display(),
                'location':      employee.location.name if employee.location else None,
                'location_id':   employee.location.id   if employee.location else None,
                'total_present': total_present,
                'total_late':    total_late,
                'total_absent':  total_absent,
            })

        # ── Paginate ──────────────────────────────────────────────
        paginator      = PageNumberPagination()
        page           = paginator.paginate_queryset(summary, request)
        paginated_data = paginator.get_paginated_response(page).data

        return Response({
            'view':           'summary',
            'period':         period,
            'period_label':   period_label,
            'employees':      paginated_data,   
        }, status=status.HTTP_200_OK)

    # ================================================================
    # DETAIL VIEW — single employee daily breakdown
    # ================================================================
    def _detail_view(self, request, employee, start_date, days_in_period, period, period_label, filter_options, now):
        records        = Attendance.objects.filter(
            user      = employee,
            date__gte = start_date.date()
        ).order_by('date')

        # ── Stat cards ────────────────────────────────────────────
        total_present = records.filter(status='present').count()
        total_late    = records.filter(status='late').count()
        total_absent  = records.filter(status='absent').count()

        # ── Count weekdays in period ──────────────────────────────
        total_weekdays = sum(
            1 for i in range(days_in_period)
            if (now - timedelta(days=i)).date().weekday() < 5
        )

        # ── Build daily log ───────────────────────────────────────
        attendance_map = {r.date: r for r in records}
        daily_log      = []

        for i in range(days_in_period - 1, -1, -1):
            day        = (now - timedelta(days=i)).date()
            record     = attendance_map.get(day)
            is_weekend = day.weekday() >= 5

            if is_weekend:
                day_status = 'weekend'
            elif record:
                day_status = record.status
            else:
                day_status = 'absent'

            daily_log.append({
                'date':         str(day),
                'date_display': day.strftime('%b %d, %Y'),
                'role':          employee.get_role_display(),
                'status':       day_status,
                'location':      employee.location.name if employee.location else None,

            })

        # ── Paginate daily log ────────────────────────────────────
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
                'total_present':  total_present,
                'total_late':     total_late,
                'total_absent':   total_absent,
                'total_weekdays': total_weekdays,
                'period_label':   period_label,
            },
            'attendance_log':  paginated_data,
        }, status=status.HTTP_200_OK)
