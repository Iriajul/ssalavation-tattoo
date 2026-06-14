# apps/users/views.py
from django.db.models import Count, Case, When, IntegerField
from rest_framework import filters, status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from apps.admin_api.models import Attendance, Instruction, QRSession, Task, UserWorkSchedule, ActivityLog   
from .models import AppNotification

from .serializers import (
    AppLoginSerializer,
    AppTaskDetailSerializer,
    AppTaskListSerializer,
    AppTaskHistoryListSerializer,
    AppTaskHistoryDetailSerializer,
    AppInstructionDetailSerializer,
    AppInstructionListSerializer,
    VerifyLoginOTPSerializer,
    ResendLoginOTPSerializer,
    AppForgotPasswordSerializer,
    AppVerifyResetOTPSerializer,
    AppResetPasswordSerializer,
    AppUserSerializer,
)

EMPLOYEE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_temp_token(user, minutes=10):
    """Short-lived token to carry user identity between OTP steps"""
    refresh = RefreshToken.for_user(user)
    refresh.access_token.set_exp(lifetime=timedelta(minutes=minutes))
    return str(refresh.access_token)


def get_user_from_temp_token(temp_token):
    """Decode temp token and return user"""
    untyped_token = UntypedToken(temp_token)
    user_id       = untyped_token.payload.get('user_id')
    return User.objects.get(id=user_id)


def send_otp_email(email, otp, subject="Salvation Tattoo — Login Code"):
    try:
        send_mail(
            subject=subject,
            message=f"Your 5-digit code is: {otp}\n\nThis code will expire in 10 minutes.\n\nIf you didn't request this, please ignore.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as e:
        print(f"Email sending failed: {e}")

def today_start(now):
    """Returns date 7 days ago for recent attendance fetch"""
    return (now - timedelta(days=7)).date()
# ================================================================
# STEP 1 — LOGIN (validates credentials → sends OTP)
# ================================================================

class AppLoginView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AppLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        otp  = user.set_login_otp()

        send_otp_email(user.email, otp, subject="Salvation Tattoo — Login Code")

        return Response({
            "message":    "A verification code has been sent to your email.",
            "email":      user.email,
            "temp_token": get_temp_token(user, minutes=10),
        }, status=status.HTTP_200_OK)


# ================================================================
# STEP 2 — VERIFY LOGIN OTP (→ returns full JWT tokens)
# ================================================================

class VerifyLoginOTPView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = VerifyLoginOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token = serializer.validated_data['temp_token']
        otp        = serializer.validated_data['otp']

        try:
            user = get_user_from_temp_token(temp_token)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired session. Please login again."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.verify_login_otp(otp):
            return Response(
                {"error": "Invalid or expired OTP."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Issue full JWT tokens
        refresh = RefreshToken.for_user(user)
        refresh['role']  = user.role
        refresh['email'] = user.email

        return Response({
            "message": "Login successful.",
            "user":    AppUserSerializer(user).data,
            "tokens": {
                "access":  str(refresh.access_token),
                "refresh": str(refresh),
            },
        }, status=status.HTTP_200_OK)


# ================================================================
# RESEND LOGIN OTP
# ================================================================

class ResendLoginOTPView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = ResendLoginOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token = serializer.validated_data['temp_token']

        try:
            user = get_user_from_temp_token(temp_token)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired session. Please login again."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        otp = user.set_login_otp()
        send_otp_email(user.email, otp, subject="Salvation Tattoo — Login Code (Resent)")

        # Issue a fresh temp token with new 10min expiry
        return Response({
            "message":    "A new verification code has been sent to your email.",
            "temp_token": get_temp_token(user, minutes=10),
        }, status=status.HTTP_200_OK)


# ================================================================
# FORGOT PASSWORD — Send OTP
# ================================================================

class AppForgotPasswordView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AppForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        user  = User.objects.get(email=email)
        otp   = user.set_reset_otp()

        send_otp_email(
            user.email, otp,
            subject="Salvation Tattoo — Password Reset Code"
        )

        return Response({
            "message":    "A reset code has been sent to your email.",
            "email":      user.email,
            "temp_token": get_temp_token(user, minutes=15),
        }, status=status.HTTP_200_OK)


# ================================================================
# VERIFY RESET OTP
# ================================================================

class AppVerifyResetOTPView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AppVerifyResetOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token = serializer.validated_data['temp_token']
        otp        = serializer.validated_data['otp']

        try:
            user = get_user_from_temp_token(temp_token)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired session. Please try again."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.verify_reset_otp(otp):
            return Response(
                {"error": "Invalid or expired OTP."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Issue a fresh temp token for reset password step
        return Response({
            "message":    "OTP verified. You can now reset your password.",
            "temp_token": get_temp_token(user, minutes=15),
        }, status=status.HTTP_200_OK)


# ================================================================
# RESET PASSWORD
# ================================================================

class AppResetPasswordView(APIView):
    permission_classes     = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = AppResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        temp_token   = serializer.validated_data['temp_token']
        new_password = serializer.validated_data['new_password']

        try:
            user = get_user_from_temp_token(temp_token)
        except (InvalidToken, User.DoesNotExist, Exception):
            return Response(
                {"error": "Invalid or expired session. Please try again."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        user.set_password(new_password)
        user.save(update_fields=['password'])

        return Response({
            "message": "Password reset successfully. Please login with your new password.",
        }, status=status.HTTP_200_OK)
    



# ================================================================
# APP — ATTENDANCE (Check In / Check Out — unified)
# ================================================================

class AppAttendanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user  = request.user
        token = request.data.get('token')

        # ── Role check ────────────────────────────────────────────
        if user.role not in EMPLOYEE_ROLES:
            return Response(
                {'error': 'Only employees can check in/out.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Token required ────────────────────────────────────────
        if not token:
            return Response(
                {'error': 'QR token is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Validate QR session ───────────────────────────────────
        try:
            qr_session = QRSession.objects.select_related('location').get(
                token     = token,
                is_active = True,
            )
        except QRSession.DoesNotExist:
            return Response(
                {'error': 'Invalid or expired QR code. Please ask your manager to regenerate.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Check if QR is expired ────────────────────────────────
        if qr_session.is_expired:
            qr_session.is_active = False
            qr_session.save(update_fields=['is_active'])
            return Response(
                {'error': 'QR code has expired. Please ask your manager to regenerate.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Employee must belong to this location ─────────────────
        if user.location != qr_session.location:
            return Response(
                {'error': 'This QR code is not for your location.'},
                status=status.HTTP_403_FORBIDDEN
            )

        today      = timezone.localdate()
        now        = timezone.localtime()
        now_time   = now.time()
        attendance = Attendance.objects.filter(user=user, date=today).first()

        # ── CHECK OUT — already checked in, no checkout yet ───────
        if attendance and attendance.clock_in:
            if attendance.clock_out:
                return Response(
                    {'error': 'You have already checked out today.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            attendance.clock_out = now_time
            attendance.save(update_fields=['clock_out'])

            return Response({
                'action':        'checkout',
                'message':       'Checked out successfully.',
                'clock_in':      attendance.clock_in.strftime('%I:%M %p'),
                'clock_out':     now_time.strftime('%I:%M %p'),
                'date':          str(today),
                'location_name': qr_session.location.name,
            }, status=status.HTTP_200_OK)

        # ── CHECK IN — no record yet today ────────────────────────
        today_day         = now.strftime('%a').lower()[:3]
        attendance_status = 'present'

        schedule = UserWorkSchedule.objects.filter(
            user      = user,
            day       = today_day,
            is_active = True,
        ).first()

        if schedule and schedule.start_time:
            if now_time > schedule.start_time:
                attendance_status = 'late'

        attendance, _ = Attendance.objects.update_or_create(
            user = user,
            date = today,
            defaults={
                'location':   qr_session.location,
                'qr_session': qr_session,
                'clock_in':   now_time,
                'status':     attendance_status,
            }
        )

        return Response({
            'action':        'checkin',
            'message':       'Checked in successfully.',
            'status':        attendance_status,
            'clock_in':      now_time.strftime('%I:%M %p'),
            'date':          str(today),
            'location_name': qr_session.location.name,
        }, status=status.HTTP_200_OK)

class AppTodayAttendanceView(APIView):
    """Get today's attendance status for home screen"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user  = request.user
        today = timezone.localdate()

        attendance = Attendance.objects.filter(
            user=user,
            date=today
        ).first()

        if not attendance:
            return Response({
                "date":       str(today),
                "status":     "not_checked_in",
                "clock_in":   None,
                "clock_out":  None,
                "location":   user.location.name if user.location else None,
            }, status=status.HTTP_200_OK)

        return Response({
            "date":       str(today),
            "status":     attendance.status if not attendance.clock_out else "checked_out",
            "clock_in":   attendance.clock_in.strftime('%I:%M %p') if attendance.clock_in else None,
            "clock_out":  attendance.clock_out.strftime('%I:%M %p') if attendance.clock_out else None,
            "location":   attendance.location.name,
        }, status=status.HTTP_200_OK)



class AppTaskViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['title', 'description']

    def get_queryset(self):
        user     = self.request.user
        queryset = Task.objects.filter(
            assigned_to=user
        ).select_related(
            'created_by', 'location',
            'completed_by', 'approved_by', 'rejected_by'
        ).order_by('-created_at')

        # ── Status filter ─────────────────────────────────────────
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AppTaskDetailSerializer
        return AppTaskListSerializer

    def list(self, request, *args, **kwargs):
        user     = request.user
        queryset = self.filter_queryset(self.get_queryset())

        # ── Stats ─────────────────────────────────────────────────
        all_tasks  = Task.objects.filter(assigned_to=user)
        stats_data = all_tasks.aggregate(
            total           = Count('id'),
            pending         = Count(Case(When(status='pending',         then=1), output_field=IntegerField())),
            awaiting_review = Count(Case(When(status='awaiting_review', then=1), output_field=IntegerField())),
            approved        = Count(Case(When(status='approved',        then=1), output_field=IntegerField())),
            rejected        = Count(Case(When(status='rejected',        then=1), output_field=IntegerField())),
        )
        stats = stats_data
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer     = self.get_serializer(page, many=True)
            paginated_data = self.get_paginated_response(serializer.data)
            return Response({
                'stats': stats,
                'tasks': paginated_data.data,
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'stats': stats,
            'tasks': serializer.data,
        }, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        task = self.get_object()
        return Response(
            AppTaskDetailSerializer(task).data,
            status=status.HTTP_200_OK
        )

    @action(
        detail=True,
        methods=['post'],
        url_path='complete',
        parser_classes=[MultiPartParser, FormParser, JSONParser]
    )
    def complete(self, request, pk=None):
        task = self.get_object()
        user = request.user

        # ── Only assigned employee can complete ───────────────────
        if not task.assigned_to.filter(id=user.id).exists():
            return Response(
                {"error": "You can only complete tasks assigned to you."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ── Only pending or rejected tasks can be completed ───────
        if task.status not in ['pending', 'rejected']:
            return Response(
                {"error": "Only pending or rejected tasks can be completed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Photo required check ──────────────────────────────────
        if task.requires_photo:
            photo = request.FILES.get('photo')
            if not photo:
                return Response(
                    {"error": "A photo is required to complete this task."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # ── Upload to Cloudinary ──────────────────────────────
            import cloudinary.uploader
            result        = cloudinary.uploader.upload(
                photo,
                folder='task_photos/',
                chunk_size = 6000000,
            )
            task.photo_url = result['secure_url']

        # ── Mark as completed ─────────────────────────────────────
        task.status       = 'awaiting_review'   # ← change this
        task.completed_by = user
        task.completed_at = timezone.now()
        task.save(update_fields=[
            'status', 'completed_by', 'completed_at', 'photo_url'
        ])

        # ── Log activity ──────────────────────────────────────────
        from apps.admin_api.models import ActivityLog
        ActivityLog.objects.create(
            action      = 'task_completed',
            actor       = user,
            task        = task,
            target_user = user,
            message     = f'{user.get_full_name()} completed "{task.title}"'
        )

        return Response({
            "message":   "Task submitted for review.",   # ← update message
            "task_id":   task.id,
            "title":     task.title,
            "status":    task.status,                    # will now return 'awaiting_review'
            "photo_url": task.photo_url,
        }, status=status.HTTP_200_OK)


class AppInstructionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['title', 'description']

    def get_queryset(self):
        user = self.request.user
        return Instruction.objects.filter(
            role_visibility__contains=user.role
        ).order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AppInstructionDetailSerializer
        return AppInstructionListSerializer


# ================================================================
# APP — TASK HISTORY
# ================================================================

class AppTaskHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends    = [filters.SearchFilter]
    search_fields      = ['title', 'description']

    def get_queryset(self):
        user     = self.request.user
        # ── Show only tasks that are NOT pending (completed/reviewed/rejected) ──
        queryset = Task.objects.filter(
            assigned_to=user
        ).exclude(
            status='pending'
        ).select_related(
            'created_by', 'location',
            'completed_by', 'approved_by', 'rejected_by'
        ).order_by('-completed_at')

        # ── Status filter ─────────────────────────────────────────
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AppTaskHistoryDetailSerializer
        return AppTaskHistoryListSerializer

    def list(self, request, *args, **kwargs):
        user     = request.user
        queryset = self.filter_queryset(self.get_queryset())

        # ── Stats: count tasks by status ──────────────────────────
        all_history_tasks = Task.objects.filter(
            assigned_to=user
        ).exclude(status='pending')
        
        stats_data = all_history_tasks.aggregate(
            total           = Count('id'),
            awaiting_review = Count(Case(When(status='awaiting_review', then=1), output_field=IntegerField())),
            approved        = Count(Case(When(status='approved',        then=1), output_field=IntegerField())),
            rejected        = Count(Case(When(status='rejected',        then=1), output_field=IntegerField())),
        )
        stats = stats_data
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer     = self.get_serializer(page, many=True)
            paginated_data = self.get_paginated_response(serializer.data)
            return Response({
                'stats': stats,
                'tasks': paginated_data.data,
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'stats': stats,
            'tasks': serializer.data,
        }, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        task = self.get_object()
        return Response(
            AppTaskHistoryDetailSerializer(task).data,
            status=status.HTTP_200_OK
        )
    

# ================================================================
# APP — PROFILE
# ================================================================

class AppProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user  = request.user
        today = timezone.localdate()

        # ── Task stats ────────────────────────────────────────────
        stats = Task.objects.filter(assigned_to=user).aggregate(
            completed = Count(Case(When(status='approved',         then=1), output_field=IntegerField())),
            approved  = Count(Case(When(status='awaiting_review',  then=1), output_field=IntegerField())),
            pending   = Count(Case(When(status='pending',          then=1), output_field=IntegerField())),
        )

        return Response({
            'id':            user.id,
            'employee_id':   f"ISL-{user.id:04d}",
            'first_name':    user.first_name,
            'last_name':     user.last_name,
            'full_name':     f"{user.first_name} {user.last_name}".strip() or user.username,
            'username':      user.username,
            'email':         user.email,
            'phone':         user.phone,
            'role':          user.role,
            'role_display':  user.get_role_display(),
            'profile_photo': user.profile_photo,
            'location':      user.location.name if user.location else None,
            'joined':        user.date_joined.strftime('%B %Y'),
            'is_active':     user.is_active,
            'is_suspended':  user.is_suspended,
            'stats': {
                'completed': stats['completed'],   # approved by admin
                'approved':  stats['approved'],    # awaiting review
                'pending':   stats['pending'],
            },
        }, status=status.HTTP_200_OK)


# ================================================================
# APP — MY PERFORMANCE
# ================================================================

class AppPerformanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user   = request.user
        period = request.query_params.get('period', 'weekly')
        today  = timezone.localdate()

        # ── Period range ──────────────────────────────────────────
        if period == 'monthly':
            # current month from day 1
            start_date = today.replace(day=1)
        else:  # weekly — last 7 days
            start_date = today - timedelta(days=6)

        # ── Task stats for period ─────────────────────────────────
        period_tasks = Task.objects.filter(
            assigned_to = user,
            created_at__date__gte = start_date,
        )

        stats = period_tasks.aggregate(
            total     = Count('id'),
            completed = Count(Case(When(status='approved',  then=1), output_field=IntegerField())),
            pending   = Count(Case(When(status='pending',   then=1), output_field=IntegerField())),
            rejected  = Count(Case(When(status='rejected',  then=1), output_field=IntegerField())),
        )

        total            = stats['total']
        completion_rate  = round((stats['completed'] / total * 100)) if total > 0 else 0

        # ── Attendance rate for period ────────────────────────────
        # Get employee's scheduled work days
        work_days = set(
            UserWorkSchedule.objects.filter(
                user      = user,
                is_active = True,
            ).values_list('day', flat=True)
        )

        WEEKDAY_MAP = {0:'mon', 1:'tue', 2:'wed', 3:'thu', 4:'fri', 5:'sat', 6:'sun'}

        # Count scheduled days in period
        scheduled_days = sum(
            1 for i in range((today - start_date).days + 1)
            if WEEKDAY_MAP[(start_date + timedelta(days=i)).weekday()] in work_days
        )

        # Count attended days (present + late)
        attended_days = Attendance.objects.filter(
            user      = user,
            date__gte = start_date,
            date__lte = today,
            status__in = ['present', 'late'],
        ).count()

        attendance_rate = round((attended_days / scheduled_days * 100)) if scheduled_days > 0 else 0
        attendance_rate = min(attendance_rate, 100)

        # ── Bar chart — daily task trend ──────────────────────────
        chart_rows = Task.objects.filter(
            assigned_to       = user,
            created_at__date__gte = start_date,
            created_at__date__lte = today,
        ).values('created_at__date').annotate(
            completed = Count(Case(When(status='approved', then=1), output_field=IntegerField())),
            pending   = Count(Case(When(status='pending',  then=1), output_field=IntegerField())),
        )
        chart_map = {row['created_at__date']: row for row in chart_rows}

        trend = []
        total_days = (today - start_date).days + 1
        for i in range(total_days):
            day  = start_date + timedelta(days=i)
            data = chart_map.get(day, {})
            trend.append({
                'date':      str(day),
                'day':       day.strftime('%a') if period == 'weekly' else str(day.day),
                'completed': data.get('completed', 0),
                'pending':   data.get('pending',   0),
            })

        return Response({
            'period': period,
            'stats': {
                'completed':       stats['completed'],
                'pending':         stats['pending'],
                'rejected':        stats['rejected'],
                'completion_rate': completion_rate,
                'attendance_rate': attendance_rate,
            },
            'trend': trend,
        }, status=status.HTTP_200_OK)


# ================================================================
# APP — UPDATE PROFILE PHOTO
# ================================================================

class AppProfilePhotoView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def patch(self, request):
        user  = request.user
        photo = request.FILES.get('profile_photo')

        if not photo:
            return Response(
                {'error': 'No photo provided.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            photo,
            folder     = 'profile_photos/',
            chunk_size = 6000000,
        )

        user.profile_photo = result['secure_url']
        user.save(update_fields=['profile_photo'])

        return Response({
            'message':       'Profile photo updated successfully.',
            'profile_photo': user.profile_photo,
        }, status=status.HTTP_200_OK)
    


# ================================================================
# APP — HOME
# ================================================================

class AppHomeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user  = request.user
        now   = timezone.localtime()
        today = timezone.localdate()

        # ── Greeting ──────────────────────────────────────────────
        hour = now.hour
        if hour < 12:   greeting = "Good morning"
        elif hour < 17: greeting = "Good afternoon"
        else:           greeting = "Good evening"

        # ── Today's attendance ────────────────────────────────────
        attendance = Attendance.objects.filter(user=user, date=today).first()

        if not attendance:
            attendance_data = {
                'status':    'not_checked_in',
                'clock_in':  None,
                'clock_out': None,
            }
        else:
            attendance_data = {
                'status':    attendance.status if not attendance.clock_out else 'checked_out',
                'clock_in':  attendance.clock_in.strftime('%I:%M %p') if attendance.clock_in else None,
                'clock_out': attendance.clock_out.strftime('%I:%M %p') if attendance.clock_out else None,
            }

        # ── Today's tasks ─────────────────────────────────────────
        today_tasks = Task.objects.filter(
            assigned_to = user,
            due_date    = today,
        ).select_related('created_by', 'location').order_by('due_date')

        task_stats = today_tasks.aggregate(
            total     = Count('id'),
            pending   = Count(Case(When(status='pending',  then=1), output_field=IntegerField())),
            completed = Count(Case(When(status='approved', then=1), output_field=IntegerField())),
        )

        # One upcoming pending task preview
        upcoming_task = today_tasks.filter(status='pending').first()
        upcoming_task_data = None
        if upcoming_task:
            upcoming_task_data = {
                'id':       upcoming_task.id,
                'title':    upcoming_task.title,
                'due_date': upcoming_task.due_date.strftime('%b %d, %Y'),
                'status':   upcoming_task.status,
            }

        return Response({
            'greeting':   f"{greeting},",
            'full_name':  f"{user.first_name} {user.last_name}".strip() or user.username,
            'attendance': attendance_data,
            'tasks': {
                'pending':   task_stats['pending'],
                'completed': task_stats['completed'],
                'total':     task_stats['total'],
                'upcoming':  upcoming_task_data,
            },
        }, status=status.HTTP_200_OK)


# ================================================================
# APP — RECENT ACTIVITY
# ================================================================

class AppRecentActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user  = request.user
        now   = timezone.now()

        # ── Task activity from ActivityLog ────────────────────────
        task_logs = ActivityLog.objects.filter(
            target_user = user,
        ).select_related('task').order_by('-created_at')[:5]

        task_activities = []
        for log in task_logs:
            task_title = f"'{log.task.title}'" if log.task else ''

            if log.action == 'task_completed':
                message = f"You submitted '{log.task.title}' for review"
                dot     = 'yellow'
            elif log.action == 'task_approved':
                message = f"Task {task_title} was approved"
                dot     = 'green'
            elif log.action == 'task_rejected':
                message = f"Task {task_title} was rejected"
                dot     = 'red'
            elif log.action == 'task_assigned':
                message = f"New task assigned: {task_title}"
                dot     = 'orange'
            else:
                message = log.message
                dot     = 'grey'

            task_activities.append({
                'type':       log.action,
                'message':    message,
                'dot':        dot,
                'created_at': log.created_at,
                'time_ago':   self._time_ago(log.created_at, now),
            })

        # ── Attendance activity from Attendance model ─────────────
        recent_attendances = Attendance.objects.filter(
            user      = user,
            date__gte = today_start(now),
        ).order_by('-date')[:10]

        att_activities = []
        for att in recent_attendances:
            if att.clock_out:
                att_activities.append({
                    'type':       'checked_out',
                    'message':    f"You checked out at {att.clock_out.strftime('%I:%M %p')}",
                    'dot':        'grey',
                    'created_at': timezone.make_aware(
                        timezone.datetime.combine(att.date, att.clock_out)
                    ),
                    'time_ago':   self._time_ago(
                        timezone.make_aware(timezone.datetime.combine(att.date, att.clock_out)), now
                    ),
                })
            if att.clock_in:
                att_activities.append({
                    'type':       'checked_in',
                    'message':    f"You checked in at {att.clock_in.strftime('%I:%M %p')}",
                    'dot':        'green',
                    'created_at': timezone.make_aware(
                        timezone.datetime.combine(att.date, att.clock_in)
                    ),
                    'time_ago':   self._time_ago(
                        timezone.make_aware(timezone.datetime.combine(att.date, att.clock_in)), now
                    ),
                })

        # ── Merge and sort by time ────────────────────────────────
        all_activities = sorted(
            task_activities + att_activities,
            key     = lambda x: x['created_at'],
            reverse = True,
        )[:20]

        # Remove created_at from response — frontend doesn't need raw datetime
        for a in all_activities:
            del a['created_at']

        return Response({
            'activities': all_activities,
        }, status=status.HTTP_200_OK)

    def _time_ago(self, dt, now):
        diff = now - dt
        seconds = int(diff.total_seconds())

        if seconds < 60:
            return 'Just now'
        elif seconds < 3600:
            m = seconds // 60
            return f"{m}m ago"
        elif seconds < 86400:
            h = seconds // 3600
            return f"{h}h ago"
        elif seconds < 172800:
            return 'Yesterday'
        else:
            days = seconds // 86400
            return f"{days}d ago"



# ================================================================
# APP — NOTIFICATIONS
# ================================================================

class AppNotificationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        tab  = request.query_params.get('tab', 'all')  # all / unread

        notifs = AppNotification.objects.filter(recipient=user)

        if tab == 'unread':
            notifs = notifs.filter(is_read=False)

        unread_count = AppNotification.objects.filter(
            recipient = user,
            is_read   = False,
        ).count()

        now  = timezone.now()
        data = [
            {
                'id':       n.id,
                'type':     n.notif_type,
                'title':    n.title,
                'message':  n.message,
                'is_read':  n.is_read,
                'task_id':  n.task.id if n.task else None,
                'time_ago': self._time_ago(n.created_at, now),
            }
            for n in notifs
        ]

        return Response({
            'unread_count':  unread_count,
            'notifications': data,
        }, status=status.HTTP_200_OK)

    def _time_ago(self, dt, now):
        seconds = int((now - dt).total_seconds())
        if seconds < 60:       return 'Just now'
        elif seconds < 3600:   return f"{seconds // 60}m ago"
        elif seconds < 86400:  return f"{seconds // 3600}h ago"
        elif seconds < 172800: return 'Yesterday'
        else:                  return f"{seconds // 86400}d ago"


class AppNotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        AppNotification.objects.filter(
            recipient = request.user,
            is_read   = False,
        ).update(is_read=True)

        return Response(
            {'message': 'All notifications marked as read.'},
            status=status.HTTP_200_OK
        )


class AppNotificationDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            notif = AppNotification.objects.get(pk=pk, recipient=request.user)
            notif.delete()
            return Response(
                {'message': 'Notification deleted.'},
                status=status.HTTP_200_OK
            )
        except AppNotification.DoesNotExist:
            return Response(
                {'error': 'Notification not found.'},
                status=status.HTTP_404_NOT_FOUND
            )