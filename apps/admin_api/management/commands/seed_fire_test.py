"""
Seed overdue task assignments so the fire flow can be tested on a live server.

Creates N employees, each at an active location, each with one task that is
already past its due date and marked `overdue` (so `can_fire` is true and the
fire endpoints will accept them immediately — no cron needed).

    python manage.py seed_fire_test              # 2 employees (default)
    python manage.py seed_fire_test --count 3
    python manage.py seed_fire_test --undo       # remove everything it created

Everything it creates is tagged, so --undo only removes its own data.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.admin_api.models import Location, Task, TaskAssignment
from apps.users.models import User

TAG = 'firetest'  # username/email prefix so --undo is precise


class Command(BaseCommand):
    help = "Seed overdue task assignments for testing the fire flow."

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=2)
        parser.add_argument('--undo', action='store_true')

    def handle(self, *args, **opts):
        if opts['undo']:
            return self._undo()

        count    = opts['count']
        location = Location.objects.filter(status='active').first()
        if not location:
            self.stderr.write("No active location found. Create one first.")
            return

        creator = User.objects.filter(role='super_admin', is_active=True).first()
        past    = timezone.localdate() - timedelta(days=3)

        rows = []
        with transaction.atomic():
            for i in range(1, count + 1):
                uname = f'{TAG}_emp{i}'
                emp = User.objects.create(
                    username   = uname,
                    email      = f'{uname}@example.com',
                    first_name = f'FireTest{i}',
                    last_name  = 'Employee',
                    role       = 'staff',
                    location   = location,
                    is_active  = True,
                )
                emp.set_password('FireTest123!')
                emp.save(update_fields=['password'])

                task = Task.objects.create(
                    title          = f'{TAG.upper()} overdue task {i}',
                    description     = 'Seeded overdue task for fire-flow testing.',
                    location       = location,
                    created_by     = creator,
                    due_date       = past,
                    requires_photo = False,
                )
                a = TaskAssignment.objects.create(
                    task=task, employee=emp, status='overdue',
                )
                rows.append((emp, task, a))

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {count} overdue assignment(s) at '{location.name}' (id {location.id}).\n"
        ))
        self.stdout.write("Use these with the fire endpoints:\n")
        for emp, task, a in rows:
            self.stdout.write(
                f"  employee='{emp.get_full_name()}' (id {emp.id}, {emp.email})\n"
                f"    GET  /api/admin/tasks/{task.id}/fire-info/\n"
                f"    POST /api/admin/tasks/{task.id}/fire-user/\n"
                f"         body: {{\"assignment_id\": {a.id}, \"fire_reason\": \"Failed to complete assigned task by the due date\"}}\n"
            )

    def _undo(self):
        emps  = User.objects.filter(username__startswith=f'{TAG}_')
        tasks = Task.objects.filter(title__startswith=f'{TAG.upper()} ')
        n_emp = emps.count()
        n_task = tasks.count()
        # TaskAssignment cascades from both task and employee deletion.
        tasks.delete()
        emps.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Removed {n_emp} seeded employee(s) and {n_task} seeded task(s)."
        ))
