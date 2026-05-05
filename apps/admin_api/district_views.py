from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from rest_framework.pagination import PageNumberPagination
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Count, Case, When, IntegerField, Q
from datetime import timedelta

from .models import Location, Task, Attendance
from .permissions import IsDistrictManager         
from .serializers import (
    TaskDetailSerializer,
    TaskCreateSerializer,
    TaskUpdateSerializer,
    TaskListSerializer,
    AdminChangePasswordSerializer
)

User = get_user_model()

# FIX 2: centralized role constants
EMPLOYEE_ROLES   = ['tattoo_artist', 'body_piercer', 'staff']
ASSIGNABLE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']


# ================================================================
# FIX 3: centralized location helper
# ================================================================

def get_active_locations():
    """Single source of truth for active location queryset."""
    return Location.objects.filter(status='active').order_by('name')



class DistrictManagerProfileView(APIView):
    permission_classes = [IsDistrictManager]

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
            'date_joined':   manager.date_joined,
            'last_login':    manager.last_login,
        }, status=status.HTTP_200_OK)

    def patch(self, request):
        manager = request.user
        photo = request.FILES.get('profile_photo')
        if photo:
            import cloudinary.uploader
            result = cloudinary.uploader.upload(photo, folder="profile_photos")
            manager.profile_photo = result['secure_url']
            manager.save(update_fields=['profile_photo'])
            return Response({
                "message": "Profile photo updated.",
                "profile_photo": manager.profile_photo,
            })
        allowed_fields = ['first_name', 'last_name', 'phone']
        for field in allowed_fields:
            if field in request.data:
                setattr(manager, field, request.data[field])
        manager.save()
        return Response({'message': 'Profile updated successfully.'}, status=status.HTTP_200_OK)


class DistrictManagerChangePasswordView(APIView):
    permission_classes = [IsDistrictManager]

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
# DISTRICT MANAGER — DASHBOARD
# ================================================================

class DistrictManagerDashboardView(APIView):
    permission_classes = [IsDistrictManager]

    def get(self, request):
        manager         = request.user
        location_filter = request.query_params.get('location')
        now             = timezone.now()
        today           = now.date()
        week_start      = today - timedelta(days=6)

        locations = get_active_locations()           
        loc_ids   = list(locations.values_list('id', flat=True))

        if not loc_ids:
            return Response({
                'stats':                self._empty_stats(),
                'location_performance': [],
                'weekly_task_activity': self._empty_chart(today),
                'attendance_summary':   [],
            }, status=status.HTTP_200_OK)

        # FIX 4: validate location_filter
        if location_filter and not locations.filter(id=location_filter).exists():
            return Response({'error': 'Invalid location.'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Q2: Bulk task stats per location ──────────────────────
        task_bulk_qs = (
            Task.objects
            .filter(location_id__in=loc_ids)
            .values('location_id')
            .annotate(
                total     = Count('id'),
                completed = Count(Case(When(status__in=['completed', 'approved'], then=1), output_field=IntegerField())),
                overdue   = Count(Case(When(status='overdue', then=1), output_field=IntegerField())),
            )
        )
        task_map = {row['location_id']: row for row in task_bulk_qs}

        # ── Q3: Bulk employee count per location ──────────────────
        emp_bulk_qs = (
            User.objects
            .filter(location_id__in=loc_ids, role__in=EMPLOYEE_ROLES, is_active=True)
            .values('location_id')
            .annotate(count=Count('id'))
        )
        emp_map = {row['location_id']: row['count'] for row in emp_bulk_qs}

        # ── Q4: Bulk attendance stats per location (weekly) ───────
        att_loc_qs = (
            Attendance.objects
            .filter(location_id__in=loc_ids, date__gte=week_start)
            .values('location_id', 'status')
            .annotate(total=Count('id'))
        )
        att_loc_map = {}
        for row in att_loc_qs:
            att_loc_map.setdefault(row['location_id'], {})[row['status']] = row['total']

        # ── Q5: Weekly task activity chart ────────────────────────
        chart_qs = (
            Task.objects
            .filter(location_id__in=loc_ids, created_at__date__gte=week_start)
            .values('created_at__date', 'status')
            .annotate(total=Count('id'))
        )
        chart_map = {}
        for row in chart_qs:
            chart_map.setdefault(row['created_at__date'], {})[row['status']] = row['total']

        weekly_task_activity = []
        for i in range(6, -1, -1):
            day      = today - timedelta(days=i)
            day_data = chart_map.get(day, {})
            weekly_task_activity.append({
                'date':      str(day),
                'day':       day.strftime('%a'),
                'assigned': (
                    day_data.get('pending',        0) +
                    day_data.get('completed',       0) +
                    day_data.get('approved',        0) +
                    day_data.get('overdue',         0) +
                    day_data.get('rejected',        0) +
                    day_data.get('awaiting_review', 0)
                ),
                'completed': day_data.get('completed', 0) + day_data.get('approved', 0),
            })

        # ── Location performance cards ────────────────────────────
        location_performance = []
        total_tasks_all      = 0
        total_done_all       = 0
        total_overdue_all    = 0

        for loc in locations:
            t = task_map.get(loc.id, {})
            a = att_loc_map.get(loc.id, {})

            total     = t.get('total',     0)
            completed = t.get('completed', 0)
            overdue   = t.get('overdue',   0)

            task_rate = round((completed / total * 100)) if total > 0 else 0
            attended  = a.get('present', 0) + a.get('late', 0)
            att_total = a.get('present', 0) + a.get('late', 0) + a.get('absent', 0)
            att_rate  = round((attended / att_total * 100)) if att_total > 0 else 0

            total_tasks_all   += total
            total_done_all    += completed
            total_overdue_all += overdue

            location_performance.append({
                'location_id':     loc.id,
                'location_name':   loc.name,
                'city_state':      loc.city_state,
                'status':          loc.status,
                'staff_count':     emp_map.get(loc.id, 0),
                'task_completion': task_rate,
                'attendance_rate': att_rate,
                'overdue_count':   overdue,
            })

        # ── Top stats ─────────────────────────────────────────────
        global_task_rate = round(
            (total_done_all / total_tasks_all * 100)
        ) if total_tasks_all > 0 else 0

        global_attended  = sum(v.get('present', 0) + v.get('late', 0) for v in att_loc_map.values())
        global_att_total = sum(
            v.get('present', 0) + v.get('late', 0) + v.get('absent', 0)
            for v in att_loc_map.values()
        )
        global_att_rate = round(
            (global_attended / global_att_total * 100)
        ) if global_att_total > 0 else 0

        top_stats = {
            'active_locations':       len(loc_ids),
            'task_completion':        global_task_rate,
            'task_completion_detail': f"{total_done_all}/{total_tasks_all} tasks done",
            'avg_attendance':         global_att_rate,
            'avg_attendance_label':   "Across all locations",
            'overdue_tasks':          total_overdue_all,
        }

        # ── Q6: Attendance summary ────────────────────────────────
        att_scope = Q(date__gte=week_start)
        if location_filter:
            att_scope &= Q(location_id=location_filter)
        else:
            att_scope &= Q(location_id__in=loc_ids)

        att_summary_qs = (
            Attendance.objects
            .filter(att_scope)
            .values('user_id', 'status')
            .annotate(total=Count('id'))
        )
        user_att_map = {}
        for row in att_summary_qs:
            user_att_map.setdefault(row['user_id'], {})[row['status']] = row['total']

        emp_scope = Q(role__in=EMPLOYEE_ROLES, is_active=True)
        if location_filter:
            emp_scope &= Q(location_id=location_filter)
        else:
            emp_scope &= Q(location_id__in=loc_ids)

        summary_employees = (
            User.objects
            .filter(emp_scope)
            .select_related('location')
            .order_by('first_name')
        )

        attendance_summary = []
        for emp in summary_employees:
            d = user_att_map.get(emp.id, {})
            attendance_summary.append({
                'id':            emp.id,
                'name':          f"{emp.first_name} {emp.last_name}".strip(),
                'location_name': emp.location.name if emp.location else None,
                'present':       d.get('present', 0),
                'late':          d.get('late',    0),
                'absent':        d.get('absent',  0),
            })

        hour = now.hour
        if hour < 12:   greet = "Good morning"
        elif hour < 17: greet = "Good afternoon"
        else:           greet = "Good evening"

        return Response({
            'greeting':     f"{greet}, {manager.first_name or 'District Manager'} 👋",
            'date_display': today.strftime('%A, %B %d, %Y'),
            'manager': {
                'id':            manager.id,
                'name':          manager.get_full_name(),
                'role_display':  manager.get_role_display(),
                'profile_photo': manager.profile_photo,
            },
            'stats':                top_stats,
            'location_performance': location_performance,
            'weekly_task_activity': weekly_task_activity,
            'attendance_summary':   attendance_summary,
        }, status=status.HTTP_200_OK)

    def _empty_stats(self):
        return {
            'active_locations':       0,
            'task_completion':        0,
            'task_completion_detail': '0/0 tasks done',
            'avg_attendance':         0,
            'avg_attendance_label':   'Across all locations',
            'overdue_tasks':          0,
        }

    def _empty_chart(self, today):
        return [
            {
                'date':      str(today - timedelta(days=i)),
                'day':       (today - timedelta(days=i)).strftime('%a'),
                'assigned':  0,
                'completed': 0,
            }
            for i in range(6, -1, -1)
        ]


# ================================================================
# DISTRICT MANAGER — TASKS
# ================================================================

class DistrictManagerTaskView(APIView):
    permission_classes = [IsDistrictManager]

    def get(self, request):
        location_filter = request.query_params.get('location')
        search          = request.query_params.get('search', '').strip()

        locations = get_active_locations()           # FIX 3
        loc_ids   = list(locations.values_list('id', flat=True))

        # FIX 4: validate location_filter
        if location_filter and not locations.filter(id=location_filter).exists():
            return Response({'error': 'Invalid location.'}, status=status.HTTP_400_BAD_REQUEST)

        task_qs = (
            Task.objects
            .filter(status='pending', location_id__in=loc_ids)
            .select_related(
                'location', 'assigned_to', 'completed_by',
                'approved_by', 'rejected_by', 'created_by'
            )
            .order_by('-created_at')
        )

        if location_filter:
            task_qs = task_qs.filter(location_id=location_filter)

        if search:
            task_qs = task_qs.filter(
                Q(title__icontains=search)                   |
                Q(description__icontains=search)             |
                Q(assigned_to__first_name__icontains=search) |
                Q(assigned_to__last_name__icontains=search)
            )

        stats_qs = Task.objects.filter(location_id__in=loc_ids)

        stats = stats_qs.aggregate(
            total   = Count('id'),
            pending = Count(Case(When(status='pending', then=1), output_field=IntegerField())),
            overdue = Count(Case(When(status='overdue', then=1), output_field=IntegerField())),
        )

        paginator           = PageNumberPagination()
        paginator.page_size = 5
        page                = paginator.paginate_queryset(task_qs, request)
        serializer          = TaskListSerializer(page, many=True)
        paginated           = paginator.get_paginated_response(serializer.data).data

        return Response({
            'stats': {
                'total':   stats['total'],
                'pending': stats['pending'],
                'overdue': stats['overdue'],
            },
            'tasks':      paginated['results'],
            'tasks_meta': {
                'count':    paginated['count'],
                'next':     paginated['next'],
                'previous': paginated['previous'],
            },
        }, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = TaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(created_by=request.user)
        return Response({
            'message': 'Task created successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_201_CREATED)


# ================================================================
# DISTRICT MANAGER — TASK DETAIL
# ================================================================

class DistrictManagerTaskDetailView(APIView):
    permission_classes = [IsDistrictManager]

    def _get_task(self, pk, loc_ids):
        try:
            return Task.objects.select_related(
                'location', 'assigned_to', 'created_by'
            ).get(pk=pk, location_id__in=loc_ids)
        except Task.DoesNotExist:
            return None

    def _get_loc_ids(self):
        return list(get_active_locations().values_list('id', flat=True))  # FIX 3

    def patch(self, request, pk):
        task = self._get_task(pk, self._get_loc_ids())
        if not task:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)
        if task.status != 'pending':
            return Response({'error': 'Only pending tasks can be edited.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = TaskUpdateSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response({
            'message': 'Task updated successfully.',
            'task':    TaskDetailSerializer(task).data,
        }, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        task = self._get_task(pk, self._get_loc_ids())
        if not task:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)
        if task.status != 'pending':
            return Response({'error': 'Only pending tasks can be deleted.'}, status=status.HTTP_400_BAD_REQUEST)
        task.delete()
        return Response({'message': 'Task deleted successfully.'}, status=status.HTTP_200_OK)


# ================================================================
# DISTRICT MANAGER — EMPLOYEES BY LOCATION
# ================================================================

class DistrictManagerLocationEmployeesView(APIView):
    permission_classes = [IsDistrictManager]

    def get(self, request, pk):
        # FIX 3: use helper
        location = get_active_locations().filter(pk=pk).first()
        if not location:
            return Response({'error': 'Location not found.'}, status=status.HTTP_404_NOT_FOUND)

        employees = (
            User.objects
            .filter(location=location, role__in=ASSIGNABLE_ROLES, is_active=True)
            .order_by('first_name')
        )

        return Response({
            'location_id':   location.id,
            'location_name': location.name,
            'employees': [
                {
                    'id':   emp.id,
                    'name': f"{emp.first_name} {emp.last_name}".strip(),
                    'role': emp.get_role_display(),
                }
                for emp in employees
            ],
        }, status=status.HTTP_200_OK)


# ================================================================
# DISTRICT MANAGER — VERIFICATIONS
# ================================================================

class DistrictManagerVerificationView(APIView):
    permission_classes = [IsDistrictManager]

    def get(self, request):
        tab             = request.query_params.get('tab', 'awaiting_review')
        location_filter = request.query_params.get('location')

        locations = get_active_locations()           # FIX 3
        loc_ids   = list(locations.values_list('id', flat=True))

        # FIX 4: validate location_filter
        if location_filter and not locations.filter(id=location_filter).exists():
            return Response({'error': 'Invalid location.'}, status=status.HTTP_400_BAD_REQUEST)

        base_tasks = Task.objects.filter(
            location_id__in=loc_ids
        ).select_related(
            'location', 'assigned_to', 'approved_by', 'rejected_by', 'created_by'
        )

        if location_filter:
            base_tasks = base_tasks.filter(location_id=location_filter)

        stats_data = base_tasks.aggregate(
            awaiting_review = Count(Case(When(status='awaiting_review', then=1), output_field=IntegerField())),
            approved        = Count(Case(When(status='approved',        then=1), output_field=IntegerField())),
            pending         = Count(Case(When(status='pending',         then=1), output_field=IntegerField())),
            overdue         = Count(Case(When(status='overdue',         then=1), output_field=IntegerField())),
            rejected        = Count(Case(When(status='rejected',        then=1), output_field=IntegerField())),
        )

        TAB_STATUS_MAP  = {
            'pending':         'pending',
            'awaiting_review': 'awaiting_review',
            'approved':        'approved',
            'rejected':        'rejected',
            'overdue':         'overdue',
        }
        selected_status = TAB_STATUS_MAP.get(tab, 'awaiting_review')
        tasks           = base_tasks.filter(status=selected_status).order_by('-created_at')

        paginator           = PageNumberPagination()
        paginator.page_size = 10
        page                = paginator.paginate_queryset(tasks, request)

        data = []
        for task in page:
            data.append({
                'id':             task.id,
                'title':          task.title,
                'description':    task.description,
                'requires_photo': task.requires_photo,
                'photo_url':      task.photo_url,
                'status':         task.status,
                'due_date':       task.due_date,
                'location': {
                    'id':   task.location.id,
                    'name': task.location.name,
                } if task.location else None,
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
            })

        return Response({
            'stats': stats_data,
            'tab':   tab,
            'tasks': paginator.get_paginated_response(data).data,
            'filter_options': {
                'locations': list(locations.values('id', 'name'))
            },
        }, status=status.HTTP_200_OK)


# ================================================================
# DISTRICT MANAGER — VERIFICATION ACTIONS
# ================================================================

class DistrictManagerVerificationActionView(APIView):
    permission_classes = [IsDistrictManager]

    def _get_task(self, pk, loc_ids):
        try:
            return Task.objects.select_related('assigned_to').get(
                pk=pk, location_id__in=loc_ids
            )
        except Task.DoesNotExist:
            return None

    def post(self, request, pk, action):
        loc_ids = list(get_active_locations().values_list('id', flat=True))  # FIX 3
        task    = self._get_task(pk, loc_ids)

        if not task:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)

        if action == 'approve':
            if task.status not in ['awaiting_review', 'rejected']:
                return Response(
                    {'error': 'Only awaiting review or rejected tasks can be approved.'},
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

        elif action == 'reject':
            rejection_reason = request.data.get('rejection_reason', '').strip()
            if not rejection_reason:
                return Response(
                    {'error': 'Rejection reason is required.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if len(rejection_reason) < 5:
                return Response(
                    {'error': 'Rejection reason must be at least 5 characters.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if task.status not in ['awaiting_review', 'approved']:
                return Response(
                    {'error': 'Only awaiting review or approved tasks can be rejected.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            task.status           = 'rejected'
            task.rejected_by      = request.user
            task.rejected_at      = timezone.now()
            task.rejection_reason = rejection_reason
            task.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason'])
            return Response({
                'message': 'Task rejected.',
                'task':    TaskDetailSerializer(task).data,
            }, status=status.HTTP_200_OK)

        return Response({'error': 'Invalid action. Use approve or reject.'}, status=status.HTTP_400_BAD_REQUEST)
    

# ================================================================
# DISTRICT MANAGER — REPORTS
# ================================================================

class DistrictManagerReportsView(APIView):
    permission_classes = [IsDistrictManager]

    def get(self, request):
        manager = request.user
        period  = request.query_params.get('period', 'weekly')
        now     = timezone.now()

        # ── Period range ──────────────────────────────────────────
        if period == 'monthly':
            start_date     = now - timedelta(days=30)
            days_in_period = 30
        elif period == 'yearly':
            start_date     = now - timedelta(days=365)
            days_in_period = 365
        else:  # weekly
            start_date     = now - timedelta(days=7)
            days_in_period = 7

        # ── Working days (exclude weekends) ───────────────────────
        working_days = max(sum(
            1 for i in range(days_in_period)
            if (now - timedelta(days=i)).date().weekday() < 5
        ), 1)

        # ── Get all locations under this district manager ─────────
        # District manager sees ALL active locations
        locations = Location.objects.filter(status='active')
        location_ids = list(locations.values_list('id', flat=True))

        # ── All employees across locations ────────────────────────
        employees = User.objects.filter(
            location_id__in = location_ids,
            role__in        = EMPLOYEE_ROLES,
            is_active       = True,
        )
        emp_ids   = list(employees.values_list('id', flat=True))
        total_emp = len(emp_ids)

        # ── All tasks in period ───────────────────────────────────
        tasks = Task.objects.filter(
            location_id__in = location_ids,
            created_at__gte = start_date,
        )

        total_tasks     = tasks.count()
        completed_tasks = tasks.filter(status__in=['completed', 'approved']).count()
        overdue_tasks   = tasks.filter(status='overdue').count()
        completion_rate = round((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0

        # ── Attendance stats ──────────────────────────────────────
        attendance_records = Attendance.objects.filter(
            user_id__in = emp_ids,
            date__gte   = start_date.date(),
        )
        total_present  = attendance_records.filter(status__in=['present', 'late']).count()
        late_arrivals  = attendance_records.filter(status='late').count()
        expected_total = total_emp * working_days
        avg_attendance = round((total_present / expected_total * 100)) if expected_total > 0 else 0

        # ── Completion vs Attendance by Location chart ─────────────
        location_chart = []
        for loc in locations:
            loc_emp_ids = list(User.objects.filter(
                location  = loc,
                role__in  = EMPLOYEE_ROLES,
                is_active = True,
            ).values_list('id', flat=True))
            loc_emp_count = len(loc_emp_ids)

            loc_tasks     = tasks.filter(location=loc)
            loc_total     = loc_tasks.count()
            loc_completed = loc_tasks.filter(status__in=['completed', 'approved']).count()
            loc_completion = round((loc_completed / loc_total * 100)) if loc_total > 0 else 0

            loc_attended  = Attendance.objects.filter(
                user_id__in = loc_emp_ids,
                date__gte   = start_date.date(),
                status__in  = ['present', 'late'],
            ).count()
            loc_expected   = loc_emp_count * working_days
            loc_attendance = round((loc_attended / loc_expected * 100)) if loc_expected > 0 else 0

            location_chart.append({
                'location':        loc.name,
                'location_id':     loc.id,
                'completion':      loc_completion,
                'attendance':      loc_attendance,
            })

        # ── Location Summary table ────────────────────────────────
        location_summary = []
        for loc in locations:
            loc_emp_ids = list(User.objects.filter(
                location  = loc,
                role__in  = EMPLOYEE_ROLES,
                is_active = True,
            ).values_list('id', flat=True))
            loc_emp_count = len(loc_emp_ids)

            # Tasks done = completed/approved out of total ever assigned
            loc_all_tasks  = Task.objects.filter(location=loc)
            loc_total_ever = loc_all_tasks.count()
            loc_done       = loc_all_tasks.filter(status__in=['completed', 'approved']).count()
            loc_overdue    = loc_all_tasks.filter(status='overdue').count()
            loc_completion = round((loc_done / loc_total_ever * 100)) if loc_total_ever > 0 else 0

            loc_attended   = Attendance.objects.filter(
                user_id__in = loc_emp_ids,
                date__gte   = start_date.date(),
                status__in  = ['present', 'late'],
            ).count()
            loc_expected   = loc_emp_count * working_days
            loc_attendance = round((loc_attended / loc_expected * 100)) if loc_expected > 0 else 0

            location_summary.append({
                'location_id':     loc.id,
                'location_name':   loc.name,
                'staff_count':     loc_emp_count,
                'tasks_done':      loc_done,
                'tasks_total':     loc_total_ever,
                'tasks_display':   f"{loc_done}/{loc_total_ever}",
                'completion_rate': loc_completion,
                'attendance_rate': loc_attendance,
                'overdue_count':   loc_overdue,
            })

        # Sort by completion rate descending
        location_summary.sort(key=lambda x: x['completion_rate'], reverse=True)

        # ── Filter options ────────────────────────────────────────
        all_locations = Location.objects.filter(
            status='active'
        ).values('id', 'name')

        return Response({
            'period': period,
            'stats': {
                'task_completion_rate': completion_rate,
                'avg_attendance_rate':  avg_attendance,
                'overdue_tasks':        overdue_tasks,
                'late_arrivals':        late_arrivals,
            },
            'location_chart':   location_chart,
            'location_summary': location_summary,
        }, status=status.HTTP_200_OK)



class DistrictManagerLocationsView(APIView):
    """
    GET /api/admin/district-manager/locations/
    District manager sees all active locations with staff count
    Read only — no create/edit/delete
    """
    permission_classes = [IsDistrictManager]

    def get(self, request):
        # Single query with annotation — no N+1
        locations = Location.objects.filter(
            status='active'
        ).annotate(
            staff_count = Count(
                'users__id',
                filter=Q(users__is_active=True, users__role__in=EMPLOYEE_ROLES),
                distinct=True
            )
        ).values(
            'id', 'name', 'street_address', 'city_state', 'status', 'staff_count'
        ).order_by('-id')

        location_list = list(locations)

        return Response({
            'locations': location_list,
        }, status=status.HTTP_200_OK)

