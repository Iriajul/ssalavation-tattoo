from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from rest_framework.pagination import PageNumberPagination
from django.contrib.auth import get_user_model
from django.db.models import Count, Case, When, IntegerField, Q
from django.utils import timezone
from datetime import datetime, time, timedelta, date
from .models import Location, Task, TaskAssignment, Attendance, UserWorkSchedule, ActivityLog
from apps.users.models import AppNotification
from .permissions import IsDistrictManager
from .utils import check_file_size
from .serializers import (
    TaskDetailSerializer,
    TaskCreateSerializer,
    TaskUpdateSerializer,
    TaskApproveSerializer,
    TaskRejectSerializer,
    TaskListSerializer,
    AdminChangePasswordSerializer
)
from django.db.models import Prefetch

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
            err = check_file_size(photo)
            if err:
                return err
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

        # ── Q2: Bulk task stats per location (via assignments) ────
        task_bulk_qs = (
            TaskAssignment.objects
            .filter(task__location_id__in=loc_ids)
            .values('task__location_id')
            .annotate(
                total     = Count('id'),
                completed = Count(Case(When(status='approved', then=1), output_field=IntegerField())),
                overdue   = Count(Case(When(status='overdue',  then=1), output_field=IntegerField())),
            )
        )
        task_map = {row['task__location_id']: row for row in task_bulk_qs}

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

        # ── Q5: Weekly task activity chart (via assignments) ──────
        chart_qs = (
            TaskAssignment.objects
            .filter(task__location_id__in=loc_ids, task__created_at__date__gte=week_start)
            .values('task__created_at__date', 'status')
            .annotate(total=Count('id'))
        )
        chart_map = {}
        for row in chart_qs:
            chart_map.setdefault(row['task__created_at__date'], {})[row['status']] = row['total']

        weekly_task_activity = []
        for i in range(6, -1, -1):
            day      = today - timedelta(days=i)
            day_data = chart_map.get(day, {})
            weekly_task_activity.append({
                'date':      str(day),
                'day':       day.strftime('%a'),
                'assigned':  sum(day_data.values()),
                'completed': day_data.get('approved', 0),
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
        status_filter   = request.query_params.get('status')
        period_filter   = request.query_params.get('period')
        search          = request.query_params.get('search', '').strip()

        locations = get_active_locations()
        loc_ids   = list(locations.values_list('id', flat=True))

        if location_filter and location_filter != 'all' and not locations.filter(id=location_filter).exists():
            return Response({'error': 'Invalid location.'}, status=status.HTTP_400_BAD_REQUEST)

        task_qs = (
            Task.objects
            .filter(location_id__in=loc_ids)
            .select_related('location', 'created_by', 'template')
            .prefetch_related(
                Prefetch('assignments', queryset=TaskAssignment.objects.select_related('employee', 'approved_by', 'rejected_by'))
            )
            .order_by('-created_at')
        )

        if location_filter and location_filter != 'all':
            task_qs = task_qs.filter(location_id=location_filter)

        if status_filter and status_filter != 'all':
            task_qs = task_qs.filter(assignments__status=status_filter).distinct()

        if period_filter and period_filter not in ('all', 'none'):
            today = timezone.localdate()
            if period_filter == 'today':
                task_qs = task_qs.filter(created_at__date=today)
            elif period_filter == 'weekly':
                task_qs = task_qs.filter(created_at__date__gte=today - timedelta(days=7))
            elif period_filter == 'monthly':
                task_qs = task_qs.filter(created_at__date__gte=today - timedelta(days=30))
            elif period_filter == 'yearly':
                task_qs = task_qs.filter(created_at__date__gte=today - timedelta(days=365))

        if search:
            task_qs = task_qs.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(assignments__employee__first_name__icontains=search) |
                Q(assignments__employee__last_name__icontains=search)
            ).distinct()

        stats_data = TaskAssignment.objects.filter(task__location_id__in=loc_ids).aggregate(
            all_tasks = Count('id'),
            overdue   = Count(Case(When(status='overdue',  then=1), output_field=IntegerField())),
            completed = Count(Case(When(status='approved', then=1), output_field=IntegerField())),
            rejected  = Count(Case(When(status='rejected', then=1), output_field=IntegerField())),
        )

        paginator  = PageNumberPagination()
        page       = paginator.paginate_queryset(task_qs, request)
        serializer = TaskListSerializer(page, many=True)
        paginated  = paginator.get_paginated_response(serializer.data)

        return Response({
            'tasks': paginated.data,
            'stats': stats_data,
        }, status=status.HTTP_200_OK)

    def post(self, request):
        data = request.data.copy()
        raw  = data.get('assigned_to')
        if not isinstance(raw, list):
            data['assigned_to'] = [raw] if raw is not None else []

        serializer = TaskCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(created_by=request.user)

        for assignment in task.assignments.select_related('employee').all():
            emp = assignment.employee
            ActivityLog.objects.create(action='task_assigned', actor=request.user, task=task, target_user=emp, message=f'Task "{task.title}" assigned to {emp.get_full_name()}')
            AppNotification.objects.create(recipient=emp, notif_type='task_assigned', title='New Task Assigned', message=f"{request.user.get_full_name() or 'District Manager'} assigned you '{task.title}'", task=task)

        return Response({'message': 'Task created successfully.', 'task': TaskDetailSerializer(task).data}, status=status.HTTP_201_CREATED)

# ================================================================
# DISTRICT MANAGER — TASK DETAIL
# ================================================================

class DistrictManagerTaskDetailView(APIView):
    permission_classes = [IsDistrictManager]

    def _get_task(self, pk, loc_ids):
        try:
            return Task.objects.select_related('location', 'created_by', 'template').prefetch_related(
                Prefetch('assignments', queryset=TaskAssignment.objects.select_related('employee', 'approved_by', 'rejected_by'))
            ).get(pk=pk, location_id__in=loc_ids)
        except Task.DoesNotExist:
            return None

    def _get_loc_ids(self):
        return list(get_active_locations().values_list('id', flat=True))

    def get(self, request, pk):
        task = self._get_task(pk, self._get_loc_ids())
        if not task:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(TaskDetailSerializer(task).data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        loc_ids = self._get_loc_ids()
        task    = self._get_task(pk, loc_ids)
        if not task:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        raw  = data.get('assigned_to')
        if raw is not None:
            data['assigned_to'] = raw if isinstance(raw, list) else [raw]

        serializer = TaskUpdateSerializer(data=data, context={'task': task, 'allowed_location_ids': loc_ids})
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        for field in ['title', 'description', 'due_date', 'is_recurring', 'frequency', 'requires_photo']:
            if field in vd:
                setattr(task, field, vd[field])
        task.save()

        for emp in vd.get('_employees', []):
            assignment, created = TaskAssignment.objects.get_or_create(task=task, employee=emp)
            if created:
                ActivityLog.objects.create(action='task_assigned', actor=request.user, task=task, target_user=emp, message=f'Task "{task.title}" assigned to {emp.get_full_name()}')
                AppNotification.objects.create(recipient=emp, notif_type='task_assigned', title='New Task Assigned', message=f"{request.user.get_full_name() or 'District Manager'} assigned you '{task.title}'", task=task)

        task.refresh_from_db()
        return Response({'message': 'Task updated successfully.', 'task': TaskDetailSerializer(task).data}, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        task = self._get_task(pk, self._get_loc_ids())
        if not task:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)
        if task.assignments.exclude(status='pending').exists():
            return Response({'error': 'Cannot delete a task that has been started by employees.'}, status=status.HTTP_400_BAD_REQUEST)
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
# DISTRICT MANAGER — ALL EMPLOYEES (across all locations)
# ================================================================

class DistrictManagerEmployeesView(APIView):
    """
    GET /api/admin/district-manager/employees/
    All assignable employees across every active location.
    Optional filters: ?location=<id>  ?search=<name>
    """
    permission_classes = [IsDistrictManager]

    def get(self, request):
        search          = request.query_params.get('search', '').strip()
        location_filter = request.query_params.get('location')

        locations = get_active_locations()
        loc_ids   = list(locations.values_list('id', flat=True))

        # FIX 4: validate location_filter
        if location_filter and not locations.filter(id=location_filter).exists():
            return Response({'error': 'Invalid location.'}, status=status.HTTP_400_BAD_REQUEST)

        emp_qs = (
            User.objects
            .filter(location_id__in=loc_ids, role__in=ASSIGNABLE_ROLES, is_active=True)
            .select_related('location')
            .order_by('first_name', 'last_name')
        )

        if location_filter:
            emp_qs = emp_qs.filter(location_id=location_filter)

        if search:
            emp_qs = emp_qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        employees = [
            {
                'id':            emp.id,
                'name':          f"{emp.first_name} {emp.last_name}".strip(),
                'email':         emp.email,
                'role':          emp.role,
                'role_display':  emp.get_role_display(),
                'location_id':   emp.location.id   if emp.location else None,
                'location_name': emp.location.name if emp.location else None,
                'profile_photo': emp.profile_photo,
            }
            for emp in emp_qs
        ]

        paginator           = PageNumberPagination()
        paginator.page_size = 15
        page                = paginator.paginate_queryset(employees, request)
        paginated           = paginator.get_paginated_response(page).data

        return Response({
            'employees':      paginated['results'],
            'employees_meta': {
                'count':    paginated['count'],
                'next':     paginated['next'],
                'previous': paginated['previous'],
            },
            'filter_options': {'locations': list(locations.values('id', 'name'))},
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

        base_qs = TaskAssignment.objects.filter(
            task__location_id__in=loc_ids
        ).select_related('task', 'task__created_by', 'task__location', 'employee', 'approved_by', 'rejected_by')

        if location_filter:
            base_qs = base_qs.filter(task__location_id=location_filter)

        stats_data = base_qs.aggregate(
            awaiting_review = Count(Case(When(status='awaiting_review', then=1), output_field=IntegerField())),
            approved        = Count(Case(When(status='approved',        then=1), output_field=IntegerField())),
            pending         = Count(Case(When(status='pending',         then=1), output_field=IntegerField())),
            overdue         = Count(Case(When(status='overdue',         then=1), output_field=IntegerField())),
            rejected        = Count(Case(When(status='rejected',        then=1), output_field=IntegerField())),
        )

        selected_status = tab if tab in ['pending', 'awaiting_review', 'approved', 'rejected', 'overdue'] else 'awaiting_review'
        assignments     = base_qs.filter(status=selected_status).order_by('-task__created_at')

        paginator           = PageNumberPagination()
        paginator.page_size = 10
        page                = paginator.paginate_queryset(assignments, request)

        data = []
        for a in page:
            task = a.task
            data.append({
                'id':             task.id,
                'assignment_id':  a.id,
                'title':          task.title,
                'description':    task.description,
                'requires_photo': task.requires_photo,
                'photo_url':      a.photo_url,
                'status':         a.status,
                'due_date':       task.due_date,
                'location': {'id': task.location.id, 'name': task.location.name} if task.location else None,
                'created_by': {
                    'id':   task.created_by.id   if task.created_by else None,
                    'name': f"{task.created_by.first_name} {task.created_by.last_name}".strip() if task.created_by else None,
                    'role': task.created_by.get_role_display() if task.created_by else None,
                },
                'assigned_to': {
                    'id': a.employee.id, 'name': f"{a.employee.first_name} {a.employee.last_name}".strip(),
                    'email': a.employee.email, 'role': a.employee.role, 'role_display': a.employee.get_role_display(),
                },
                'submitted_at':     a.completed_at.strftime('%b %d, %I:%M %p') if a.completed_at else None,
                'created_at':       task.created_at,
                'approved_by':      f"{a.approved_by.first_name} {a.approved_by.last_name}".strip() if a.approved_by else None,
                'approved_at':      a.approved_at,
                'rejected_by':      f"{a.rejected_by.first_name} {a.rejected_by.last_name}".strip() if a.rejected_by else None,
                'rejected_at':      a.rejected_at,
                'rejection_reason': a.rejection_reason,
            })

        return Response({
            'stats': stats_data,
            'tab':   tab,
            'tasks': paginator.get_paginated_response(data).data,
            'filter_options': {'locations': list(locations.values('id', 'name'))},
        }, status=status.HTTP_200_OK)


# ================================================================
# DISTRICT MANAGER — VERIFICATION ACTIONS
# ================================================================

class DistrictManagerVerificationActionView(APIView):
    permission_classes = [IsDistrictManager]

    def _get_assignment(self, task_pk, assignment_id, loc_ids):
        try:
            return TaskAssignment.objects.select_related('task', 'employee').get(
                pk=assignment_id, task_id=task_pk, task__location_id__in=loc_ids
            )
        except TaskAssignment.DoesNotExist:
            return None

    def post(self, request, pk, action):
        loc_ids     = list(get_active_locations().values_list('id', flat=True))
        task_exists = Task.objects.filter(pk=pk, location_id__in=loc_ids).exists()
        if not task_exists:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)

        task = Task.objects.get(pk=pk)

        if action == 'approve':
            s = TaskApproveSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            assignment = self._get_assignment(pk, s.validated_data['assignment_id'], loc_ids)
            if not assignment:
                return Response({'error': 'Assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
            if assignment.status not in ['awaiting_review', 'rejected']:
                return Response({'error': 'Only awaiting review or rejected assignments can be approved.'}, status=status.HTTP_400_BAD_REQUEST)
            assignment.status = 'approved'; assignment.approved_by = request.user; assignment.approved_at = timezone.now(); assignment.rejection_reason = None
            assignment.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason'])
            emp = assignment.employee
            AppNotification.objects.create(recipient=emp, notif_type='task_approved', title='Task Approved', message=f"Your '{task.title}' was approved by {request.user.get_full_name() or 'District Manager'}", task=task)
            return Response({'message': 'Task approved successfully.', 'task': TaskDetailSerializer(task).data}, status=status.HTTP_200_OK)

        elif action == 'reject':
            s = TaskRejectSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            assignment = self._get_assignment(pk, s.validated_data['assignment_id'], loc_ids)
            if not assignment:
                return Response({'error': 'Assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
            if assignment.status not in ['awaiting_review', 'approved']:
                return Response({'error': 'Only awaiting review or approved assignments can be rejected.'}, status=status.HTTP_400_BAD_REQUEST)
            assignment.status = 'rejected'; assignment.rejected_by = request.user; assignment.rejected_at = timezone.now(); assignment.rejection_reason = s.validated_data['rejection_reason']
            assignment.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason'])
            emp = assignment.employee
            AppNotification.objects.create(recipient=emp, notif_type='task_rejected', title='Task Needs Revision', message=f"'{task.title}' was rejected. {s.validated_data['rejection_reason']}", task=task)
            return Response({'message': 'Task rejected.', 'task': TaskDetailSerializer(task).data}, status=status.HTTP_200_OK)

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

        working_days = max(sum(
            1 for i in range(days_in_period)
            if (now - timedelta(days=i)).date().weekday() < 5
        ), 1)

        # ── Locations — single query ──────────────────────────────
        locations    = Location.objects.filter(status='active')
        location_ids = list(locations.values_list('id', flat=True))

        if not location_ids:
            return Response({
                'period': period,
                'stats': {
                    'task_completion_rate': 0,
                    'avg_attendance_rate':  0,
                    'overdue_tasks':        0,
                    'late_arrivals':        0,
                },
                'location_chart':   [],
                'location_summary': [],
            }, status=status.HTTP_200_OK)

        # ── Bulk employee count per location — single query ───────
        emp_rows = (
            User.objects
            .filter(location_id__in=location_ids, role__in=EMPLOYEE_ROLES, is_active=True)
            .values('location_id')
            .annotate(count=Count('id'))
        )
        emp_map = {row['location_id']: row['count'] for row in emp_rows}

        # All emp ids in one shot
        all_emp_ids = list(
            User.objects
            .filter(location_id__in=location_ids, role__in=EMPLOYEE_ROLES, is_active=True)
            .values_list('id', flat=True)
        )
        total_emp = len(all_emp_ids)

        # ── Bulk task stats per location — single query ───────────
        period_task_rows = (
            TaskAssignment.objects
            .filter(task__location_id__in=location_ids, task__created_at__gte=start_date)
            .values('task__location_id')
            .annotate(
                total     = Count('id'),
                completed = Count(Case(When(status='approved', then=1), output_field=IntegerField())),
                overdue   = Count(Case(When(status='overdue',  then=1), output_field=IntegerField())),
            )
        )
        period_task_map = {row['task__location_id']: row for row in period_task_rows}

        alltime_task_rows = (
            TaskAssignment.objects
            .filter(task__location_id__in=location_ids)
            .values('task__location_id')
            .annotate(
                total     = Count('id'),
                completed = Count(Case(When(status='approved', then=1), output_field=IntegerField())),
                overdue   = Count(Case(When(status='overdue',  then=1), output_field=IntegerField())),
            )
        )
        alltime_task_map = {row['task__location_id']: row for row in alltime_task_rows}

        # Global task stats
        total_tasks     = sum(r['total']     for r in period_task_map.values())
        completed_tasks = sum(r['completed'] for r in period_task_map.values())
        overdue_tasks   = sum(r['overdue']   for r in period_task_map.values())
        completion_rate = round((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0

        # ── Bulk attendance per location — single query ───────────
        att_rows = (
            Attendance.objects
            .filter(user_id__in=all_emp_ids, date__gte=start_date.date())
            .values('location_id')
            .annotate(
                present = Count(Case(When(status='present', then=1), output_field=IntegerField())),
                late    = Count(Case(When(status='late',    then=1), output_field=IntegerField())),
                absent  = Count(Case(When(status='absent',  then=1), output_field=IntegerField())),
            )
        )
        att_map = {row['location_id']: row for row in att_rows}

        # Global attendance stats
        total_present = sum(r['present'] + r['late'] for r in att_map.values())
        late_arrivals = sum(r['late']                for r in att_map.values())
        expected_total = total_emp * working_days
        avg_attendance = round((total_present / expected_total * 100)) if expected_total > 0 else 0

        # ── Location chart & summary — no queries inside loop ─────
        location_chart   = []
        location_summary = []

        for loc in locations:
            emp_count = emp_map.get(loc.id, 0)

            # ── Chart (period tasks) ──────────────────────────────
            pt        = period_task_map.get(loc.id, {})
            pt_total  = pt.get('total',     0)
            pt_done   = pt.get('completed', 0)
            task_rate = round((pt_done / pt_total * 100)) if pt_total > 0 else 0

            a         = att_map.get(loc.id, {})
            attended  = a.get('present', 0) + a.get('late', 0)
            att_total = attended + a.get('absent', 0)
            att_rate  = round((attended / att_total * 100)) if att_total > 0 else 0

            location_chart.append({
                'location_id':   loc.id,
                'location':      loc.name,
                'completion':    task_rate,
                'attendance':    att_rate,
            })

            # ── Summary (all-time tasks) ──────────────────────────
            at        = alltime_task_map.get(loc.id, {})
            at_total  = at.get('total',     0)
            at_done   = at.get('completed', 0)
            at_overdue = at.get('overdue',  0)
            at_rate   = round((at_done / at_total * 100)) if at_total > 0 else 0

            loc_expected  = emp_count * working_days
            loc_att_rate  = round((attended / loc_expected * 100)) if loc_expected > 0 else 0

            location_summary.append({
                'location_id':     loc.id,
                'location_name':   loc.name,
                'staff_count':     emp_count,
                'tasks_done':      at_done,
                'tasks_total':     at_total,
                'tasks_display':   f"{at_done}/{at_total}",
                'completion_rate': at_rate,
                'attendance_rate': loc_att_rate,
                'overdue_count':   at_overdue,
            })

        location_summary.sort(key=lambda x: x['completion_rate'], reverse=True)

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

class DistrictManagerEmployeePerformanceView(APIView):
    permission_classes = [IsDistrictManager]

    def get(self, request):
        period          = request.query_params.get('period', 'weekly')
        location_filter = request.query_params.get('location')
        now             = timezone.now()
        today           = now.date()

        # ── Period range ──────────────────────────────────────────
        if period == 'monthly':
            start_date   = today - timedelta(days=30)
            period_label = 'month'
        elif period == 'yearly':
            start_date   = today - timedelta(days=365)
            period_label = 'year'
        else:  # weekly
            start_date   = today - timedelta(days=7)
            period_label = 'week'

        start_datetime = timezone.make_aware(
            datetime.combine(start_date, time.min)
        )
        # ── All active locations — one DB hit, reused everywhere ──
        all_locations = Location.objects.filter(status='active')
        location_list = list(all_locations.values('id', 'name'))
        location_ids  = [loc['id'] for loc in location_list]

        # ── Validate location filter ──────────────────────────────
        scoped_location_ids = location_ids
        location_label      = 'All Locations'

        if location_filter:
            try:
                location_filter_int = int(location_filter)
                if location_filter_int not in location_ids:
                    return Response(
                        {'error': 'Invalid location.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                scoped_location_ids = [location_filter_int]
                location_label      = next(
                    (loc['name'] for loc in location_list
                     if loc['id'] == location_filter_int),
                    'All Locations'
                )
            except (ValueError, TypeError):
                return Response(
                    {'error': 'location must be a valid integer.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ── FIX 1 — single query: get emp_ids first, check empty ─
        emp_ids = list(
            User.objects.filter(
                role__in        = EMPLOYEE_ROLES,
                is_active       = True,
                location_id__in = scoped_location_ids,
            ).values_list('id', flat=True)
        )

        if not emp_ids:    # FIX 1 — no second .exists() query
            return Response({
                'period':               period,
                'period_label':         period_label,
                'location_label':       location_label,
                'employee_count':       0,
                'top_performers':       [],
                'on_time_rate_chart':   [],
                'employee_performance': {'count': 0, 'next': None, 'previous': None, 'results': []},
                'filter_options':       {'locations': location_list},
            }, status=status.HTTP_200_OK)

        # ── Full employee objects — only after empty check ────────
        employees = User.objects.filter(
            id__in = emp_ids
        ).select_related('location').order_by('first_name')

        # ── Bulk task stats (via assignments) ─────────────────────
        task_rows = TaskAssignment.objects.filter(
            employee_id__in     = emp_ids,
            task__created_at__gte = start_datetime,
        ).values('employee_id').annotate(
            total_tasks     = Count('id'),
            completed_tasks = Count(
                Case(When(status='approved', then=1),
                     output_field=IntegerField())
            ),
        )
        task_map = {row['employee_id']: row for row in task_rows}

        # ── Bulk attendance stats ─────────────────────────────────
        attendance_rows = Attendance.objects.filter(
            user_id__in = emp_ids,
            date__gte   = start_date,
        ).values('user_id').annotate(
            present_count = Count(Case(When(status='present', then=1), output_field=IntegerField())),
            late_count    = Count(Case(When(status='late',    then=1), output_field=IntegerField())),
            absent_count  = Count(Case(When(status='absent',  then=1), output_field=IntegerField())),
        )
        att_map = {row['user_id']: row for row in attendance_rows}

        # ── Build performance rows ────────────────────────────────
        performance_rows = []

        for emp in employees:
            role_display = emp.get_role_display()

            # FIX 4 — cache location lookups once per employee
            loc_name = emp.location.name if emp.location else '—'
            loc_id   = emp.location.id   if emp.location else None

            task = task_map.get(emp.id, {})
            att  = att_map.get(emp.id, {})

            total_tasks     = task.get('total_tasks',     0)
            completed_tasks = task.get('completed_tasks', 0)
            present_count   = att.get('present_count',   0)
            late_count      = att.get('late_count',       0)
            absent_count    = att.get('absent_count',     0)

            # ── Task completion rate ──────────────────────────────
            task_rate = round((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0

            # ── Volume weight — sqrt scaling, needs ~16 tasks for full weight
            volume_weight       = min((total_tasks ** 0.5) / 4, 1.0)
            adjusted_task_score = task_rate * volume_weight

            # ── On-time rate — correct denominator ───────────────
            total_days   = present_count + late_count + absent_count
            on_time_rate = round((present_count / total_days * 100)) if total_days > 0 else 0
            on_time_rate = min(on_time_rate, 100)

            # ── Score = 60% adjusted task + 40% on-time ──────────
            score = round((adjusted_task_score * 0.6) + (on_time_rate * 0.4))
            score = min(score, 100)

            # ── FIX 5 — penalize low task volume performers ───────
            if total_tasks < 5:
                score = round(score * 0.7)

            performance_rows.append({
                'id':              emp.id,
                'name':            f"{emp.first_name} {emp.last_name}".strip(),
                'role':            role_display,
                'location':        loc_name,    # FIX 4 — cached variable
                'location_id':     loc_id,      # FIX 4 — cached variable
                'tasks_completed': completed_tasks,
                'tasks_total':     total_tasks,
                'tasks_display':   f"{completed_tasks}/{total_tasks}",
                'present':         present_count,
                'late_arrivals':   late_count,
                'absent':          absent_count,
                'total_days':      total_days,
                'on_time_rate':    on_time_rate,
                'task_rate':       task_rate,
                'score':           score,
            })

        # ── FIX 3 — sort by score once ────────────────────────────
        performance_rows.sort(key=lambda x: x['score'], reverse=True)

        # ── Top 3 performers ──────────────────────────────────────
        top_performers = [
            {
                'rank':     i,
                'id':       row['id'],
                'name':     row['name'],
                'role':     row['role'],
                'location': row['location'],
                'score':    row['score'],
            }
            for i, row in enumerate(performance_rows[:3], start=1)
        ]

        # ── FIX 3 — sort by on_time_rate once, reuse, slice to 20 
        sorted_by_on_time = sorted(
            performance_rows,
            key     = lambda x: x['on_time_rate'],
            reverse = True
        )
        on_time_chart = [
            {
                'name':         row['name'],
                'on_time_rate': row['on_time_rate'],
            }
            for row in sorted_by_on_time[:20]   # FIX 3 — reuse sorted list
        ]

        # ── Paginate ──────────────────────────────────────────────
        # FIX 2 note: fine under ~2k employees; future path is DB annotation
        paginator           = PageNumberPagination()
        paginator.page_size = 10
        page                = paginator.paginate_queryset(performance_rows, request)
        paginated_data      = paginator.get_paginated_response(page).data

        return Response({
            'period':          period,
            'period_label':    period_label,
            'location_filter': location_filter,
            'location_label':  location_label,
            'employee_count':  len(performance_rows),
            'top_performers':       top_performers,
            'on_time_rate_chart':   on_time_chart,
            'employee_performance': paginated_data,

        }, status=status.HTTP_200_OK)
    
class DistrictManagerPerformanceDashboardView(APIView):
    permission_classes = [IsDistrictManager]

    def get(self, request):
        # ── Locations ─────────────────────────────────────────────
        location_ids = list(
            get_active_locations().values_list('id', flat=True)
        )

        if not location_ids:
            return Response({'task_log': []}, status=status.HTTP_200_OK)

        # ── 10 most recent task assignments ───────────────────────
        task_log_qs = TaskAssignment.objects.filter(
            task__location_id__in=location_ids,
        ).select_related(
            'employee', 'task', 'task__location', 'task__created_by'
        ).order_by('-task__created_at')[:10]

        task_log = [
            {
                'id':               a.task.id,
                'assignment_id':    a.id,
                'title':            a.task.title,
                'assigned_to':      f"{a.employee.first_name} {a.employee.last_name}".strip() if a.employee else '—',
                'location':         a.task.location.name if a.task.location else '—',
                'assigned_by':      f"{a.task.created_by.first_name} {a.task.created_by.last_name}".strip() if a.task.created_by else '—',
                'assigned_by_role': a.task.created_by.get_role_display() if a.task.created_by else '—',
                'due_date':         a.task.due_date,
                'status':           a.status,
            }
            for a in task_log_qs
        ]

        return Response({'task_log': task_log}, status=status.HTTP_200_OK)
    
# ================================================================
# DISTRICT MANAGER — USER ATTENDANCE LIST (paginated)
# ================================================================

class DistrictManagerUserAttendanceListView(APIView):
    permission_classes = [IsDistrictManager]

    def get(self, request):
        search          = request.query_params.get('search', '').strip()
        location_filter = request.query_params.get('location')
        year            = request.query_params.get('year', str(timezone.now().year))

        try:
            year = int(year)
        except ValueError:
            return Response({'error': 'Invalid year.'}, status=status.HTTP_400_BAD_REQUEST)

        start_date = date(year, 1, 1)
        end_date   = date(year, 12, 31)

        # ── Validate locations ────────────────────────────────────
        all_locations = get_active_locations()
        location_ids  = list(all_locations.values_list('id', flat=True))

        if location_filter:
            try:
                location_filter = int(location_filter)
                if location_filter not in location_ids:
                    return Response({'error': 'Invalid location.'}, status=status.HTTP_400_BAD_REQUEST)
                scoped_loc_ids = [location_filter]
            except (ValueError, TypeError):
                return Response({'error': 'location must be a valid integer.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            scoped_loc_ids = location_ids

        # ── Employee queryset ─────────────────────────────────────
        emp_qs = User.objects.filter(
            role__in        = EMPLOYEE_ROLES,
            is_active       = True,
            location_id__in = scoped_loc_ids,
        ).select_related('location').order_by('first_name', 'last_name')

        if search:
            emp_qs = emp_qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        emp_ids = list(emp_qs.values_list('id', flat=True))

        # ── Bulk yearly attendance totals per employee ────────────
        att_rows = Attendance.objects.filter(
            user_id__in = emp_ids,
            date__gte   = start_date,
            date__lte   = end_date,
        ).values('user_id').annotate(
            present = Count(Case(When(status='present', then=1), output_field=IntegerField())),
            late    = Count(Case(When(status='late',    then=1), output_field=IntegerField())),
            absent  = Count(Case(When(status='absent',  then=1), output_field=IntegerField())),
        )
        att_map = {row['user_id']: row for row in att_rows}

        # ── Build rows ────────────────────────────────────────────
        employee_rows = []
        for emp in emp_qs:
            a = att_map.get(emp.id, {})
            employee_rows.append({
                'id':            emp.id,
                'name':          f"{emp.first_name} {emp.last_name}".strip(),
                'role':          emp.get_role_display(),
                'location_name': emp.location.name if emp.location else '—',
                'location_id':   emp.location.id   if emp.location else None,
                'present':       a.get('present', 0),
                'late':          a.get('late',    0),
                'absent':        a.get('absent',  0),
            })

        # ── Paginate ──────────────────────────────────────────────
        paginator           = PageNumberPagination()
        paginator.page_size = 15
        page                = paginator.paginate_queryset(employee_rows, request)
        paginated           = paginator.get_paginated_response(page).data

        return Response({
            'year':          year,
            'employees':     paginated['results'],
            'employees_meta': {
                'count':    paginated['count'],
                'next':     paginated['next'],
                'previous': paginated['previous'],
            },
        }, status=status.HTTP_200_OK)


# ================================================================
# DISTRICT MANAGER — EMPLOYEE ATTENDANCE DETAIL (drill-down)
# ================================================================
class DistrictManagerEmployeeAttendanceDetailView(APIView):
    permission_classes = [IsDistrictManager]

    WEEKDAY_MAP = {
        0: 'mon',
        1: 'tue',
        2: 'wed',
        3: 'thu',
        4: 'fri',
        5: 'sat',
        6: 'sun',
    }

    def get(self, request, employee_id):
        year_param  = request.query_params.get('year', str(timezone.now().year))
        month_param = request.query_params.get('month')  # e.g. "2025-01"

        try:
            year = int(year_param)
        except ValueError:
            return Response({'error': 'Invalid year.'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Validate employee ─────────────────────────────────────
        all_locations = get_active_locations()
        location_ids  = list(all_locations.values_list('id', flat=True))

        try:
            emp = User.objects.select_related('location').get(
                id              = employee_id,
                role__in        = EMPLOYEE_ROLES,
                is_active       = True,
                location_id__in = location_ids,
            )
        except User.DoesNotExist:
            return Response({'error': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)

        emp_info = {
            'id':       emp.id,
            'name':     f"{emp.first_name} {emp.last_name}".strip(),
            'role':     emp.get_role_display(),
            'location': emp.location.name if emp.location else '—',
        }

        # ── Fetch employee's active work days once ────────────────
        work_days = set(
            UserWorkSchedule.objects.filter(
                user      = emp,
                is_active = True,
            ).values_list('day', flat=True)
        )

        # ── MODE 1: month param given → return day grid ───────────
        if month_param:
            try:
                parsed     = datetime.strptime(month_param, '%Y-%m')
                month_year = parsed.year
                month_num  = parsed.month
                start_date = date(month_year, month_num, 1)
                if month_num == 12:
                    end_date = date(month_year, 12, 31)
                else:
                    end_date = date(month_year, month_num + 1, 1) - timedelta(days=1)
            except ValueError:
                return Response(
                    {'error': 'Invalid month format. Use YYYY-MM.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            att_qs  = Attendance.objects.filter(
                user      = emp,
                date__gte = start_date,
                date__lte = end_date,
            )
            att_map = {a.date: a for a in att_qs}

            daily_records = []
            current = start_date
            while current <= end_date:
                a           = att_map.get(current)
                day_key     = self.WEEKDAY_MAP[current.weekday()]
                is_work_day = day_key in work_days

                if a:
                    day_status = a.status
                elif is_work_day:
                    day_status = 'absent'
                else:
                    day_status = 'weekday'

                daily_records.append({
                    'date':        str(current),
                    'day':         current.day,
                    'weekday':     current.strftime('%a'),
                    'is_work_day': is_work_day,
                    'status':      day_status,  # present / late / absent / weekday
                    'clock_in':    str(a.clock_in)  if a and a.clock_in  else None,
                    'clock_out':   str(a.clock_out) if a and a.clock_out else None,
                })
                current += timedelta(days=1)

            # Only count actual work days in summary
            present = sum(1 for r in daily_records if r['status'] == 'present')
            late    = sum(1 for r in daily_records if r['status'] == 'late')
            absent  = sum(1 for r in daily_records if r['status'] == 'absent')

            return Response({
                'employee':    emp_info,
                'mode':        'daily',
                'month':       month_param,
                'month_label': parsed.strftime('%B %Y'),
                'summary': {
                    'present': present,
                    'late':    late,
                    'absent':  absent,
                },
                'records': daily_records,
            }, status=status.HTTP_200_OK)

        # ── MODE 2: no month → return 12-month summary cards ──────
        start_date = date(year, 1, 1)
        end_date   = date(year, 12, 31)

        att_qs = Attendance.objects.filter(
            user      = emp,
            date__gte = start_date,
            date__lte = end_date,
        ).values('date__month').annotate(
            present = Count(Case(When(status='present', then=1), output_field=IntegerField())),
            late    = Count(Case(When(status='late',    then=1), output_field=IntegerField())),
            absent  = Count(Case(When(status='absent',  then=1), output_field=IntegerField())),
        )
        monthly_map = {row['date__month']: row for row in att_qs}

        monthly_records = []
        for m in range(1, 13):
            data = monthly_map.get(m, {'present': 0, 'late': 0, 'absent': 0})
            monthly_records.append({
                'month':       m,
                'month_label': date(year, m, 1).strftime('%b'),
                'month_key':   f"{year}-{str(m).zfill(2)}",
                'present':     data['present'],
                'late':        data['late'],
                'absent':      data['absent'],
            })

        total_present = sum(r['present'] for r in monthly_records)
        total_late    = sum(r['late']    for r in monthly_records)
        total_absent  = sum(r['absent']  for r in monthly_records)

        return Response({
            'employee': emp_info,
            'mode':     'monthly',
            'year':     year,
            'summary': {
                'present': total_present,
                'late':    total_late,
                'absent':  total_absent,
            },
            'records': monthly_records,
        }, status=status.HTTP_200_OK)