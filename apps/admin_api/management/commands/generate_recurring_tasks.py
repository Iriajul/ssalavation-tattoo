"""
Rolling generator for recurring tasks.

Run nightly (cron or celery-beat) to keep each active RecurringTaskTemplate's
Task instances materialized for the next ~60 days. Idempotent — safe to run
repeatedly; it never creates duplicate (template, due_date) rows.

    python manage.py generate_recurring_tasks
"""

from django.core.management.base import BaseCommand

from apps.admin_api.models import RecurringTaskTemplate
from apps.admin_api.recurrence import generate_instances


class Command(BaseCommand):
    help = "Materialize upcoming Task instances for all active recurring templates."

    def add_arguments(self, parser):
        parser.add_argument(
            '--horizon', type=int, default=None,
            help='Override the generation horizon in days (default 60).',
        )

    def handle(self, *args, **options):
        templates = RecurringTaskTemplate.objects.filter(is_active=True)
        total = 0
        for template in templates:
            kwargs = {}
            if options.get('horizon'):
                kwargs['horizon_days'] = options['horizon']
            created = generate_instances(template, **kwargs)
            if created:
                total += len(created)
                self.stdout.write(
                    f"  template #{template.id} '{template.title}': +{len(created)} task(s)"
                )
        self.stdout.write(self.style.SUCCESS(
            f"Done. {templates.count()} active template(s), {total} new task(s) generated."
        ))
