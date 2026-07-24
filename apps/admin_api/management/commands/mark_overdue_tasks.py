"""
Flag assignments the employee never submitted by their due date.

Run nightly (same cron as generate_recurring_tasks) so the `overdue` status —
which dashboards count and which fire-user requires — is actually populated.

Only `pending` flips. An assignment sitting in `awaiting_review` was submitted
on time and is waiting on a manager; a slow review must never make the employee
overdue (and therefore fireable). `rejected` keeps its own manager decision.

    python manage.py mark_overdue_tasks
    python manage.py mark_overdue_tasks --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.admin_api.models import ActivityLog, TaskAssignment
from apps.users.models import AppNotification


class Command(BaseCommand):
    help = "Mark past-due unsubmitted task assignments as overdue."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing anything.',
        )

    def handle(self, *args, **options):
        today    = timezone.localdate()
        dry_run  = options['dry_run']

        stale = list(
            TaskAssignment.objects
            .filter(status='pending', task__due_date__lt=today)
            .select_related('task', 'employee')
        )

        if not stale:
            self.stdout.write(self.style.SUCCESS("No overdue assignments. Nothing to do."))
            return

        for a in stale:
            self.stdout.write(
                f"  #{a.id} '{a.task.title}' → {a.employee.get_full_name()} "
                f"(due {a.task.due_date})"
            )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"Dry run — {len(stale)} assignment(s) would be marked overdue."
            ))
            return

        with transaction.atomic():
            TaskAssignment.objects.filter(
                pk__in=[a.pk for a in stale]
            ).update(status='overdue')

            AppNotification.objects.bulk_create([
                AppNotification(
                    recipient  = a.employee,
                    notif_type = AppNotification.NotifType.TASK_DUE_SOON,
                    title      = 'Task Overdue',
                    message    = f"'{a.task.title}' was due {a.task.due_date} and is now overdue.",
                    task       = a.task,
                )
                for a in stale
            ])

            ActivityLog.objects.bulk_create([
                ActivityLog(
                    action      = ActivityLog.Action.TASK_OVERDUE,
                    task        = a.task,
                    target_user = a.employee,
                    message     = f'"{a.task.title}" became overdue for {a.employee.get_full_name()}',
                )
                for a in stale
            ])

        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(stale)} assignment(s) marked overdue and notified."
        ))
