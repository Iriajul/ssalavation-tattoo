"""
Seed demo attendance data so the Super Admin / District Manager / Branch Manager
dashboards show realistic numbers instead of zeros.

Safe to run on live: existing attendance rows are NEVER overwritten — only dates
with no record for that employee are filled in. Use --dry-run to preview first.

    python manage.py seed_attendance --days 14 --dry-run
    python manage.py seed_attendance --days 14
    python manage.py seed_attendance --days 14 --location 3
    python manage.py seed_attendance --undo --days 14     # remove seeded rows
"""
import random
from datetime import date, time, timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.admin_api.models import Attendance, UserWorkSchedule

User = get_user_model()

EMPLOYEE_ROLES = ['tattoo_artist', 'body_piercer', 'staff']
WEEKDAY_MAP = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}

# Distribution of a normal working day.
PRESENT_WEIGHT = 78
LATE_WEIGHT    = 14
ABSENT_WEIGHT  = 8

DEFAULT_START = time(10, 0)
DEFAULT_END   = time(18, 0)


def _shift(t, minutes):
    """Offset a time object by N minutes (clamped to the same day)."""
    base = timezone.datetime.combine(date(2000, 1, 1), t) + timedelta(minutes=minutes)
    return base.time()


class Command(BaseCommand):
    help = "Seed demo attendance records for employees (does not overwrite real check-ins)."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=14,
                            help='How many days back to fill, including today (default 14).')
        parser.add_argument('--location', type=int, default=None,
                            help='Only seed employees at this location id.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would be created without writing.')
        parser.add_argument('--undo', action='store_true',
                            help='Delete attendance rows in the range that have no qr_session '
                                 '(i.e. the seeded ones). Real QR check-ins are kept.')
        parser.add_argument('--seed', type=int, default=None,
                            help='Random seed, for reproducible output.')

    def handle(self, *args, **opts):
        days     = opts['days']
        loc_id   = opts['location']
        dry_run  = opts['dry_run']
        undo     = opts['undo']

        if opts['seed'] is not None:
            random.seed(opts['seed'])

        today      = timezone.localdate()
        start_date = today - timedelta(days=days - 1)

        employees = User.objects.filter(
            role__in=EMPLOYEE_ROLES, is_active=True, location__isnull=False
        ).select_related('location')
        if loc_id:
            employees = employees.filter(location_id=loc_id)

        if not employees.exists():
            self.stdout.write(self.style.WARNING('No active employees with a location found. Nothing to do.'))
            return

        # ── UNDO ──────────────────────────────────────────────────────────────
        if undo:
            seeded = Attendance.objects.filter(
                user__in=employees, date__gte=start_date, date__lte=today, qr_session__isnull=True
            )
            count = seeded.count()
            if dry_run:
                self.stdout.write(f'[dry-run] would delete {count} seeded attendance rows.')
                return
            seeded.delete()
            self.stdout.write(self.style.SUCCESS(f'Deleted {count} seeded attendance rows.'))
            return

        # ── Existing rows: never touch them ───────────────────────────────────
        existing = set(
            Attendance.objects.filter(
                user__in=employees, date__gte=start_date, date__lte=today
            ).values_list('user_id', 'date')
        )

        # ── Work schedules, so we only fill days people actually work ─────────
        schedules = {}
        for s in UserWorkSchedule.objects.filter(user__in=employees, is_active=True):
            schedules.setdefault(s.user_id, {})[s.day] = s

        to_create = []
        skipped   = 0

        for emp in employees:
            emp_sched = schedules.get(emp.id, {})

            for i in range(days):
                day = start_date + timedelta(days=i)
                if (emp.id, day) in existing:
                    skipped += 1
                    continue

                weekday = WEEKDAY_MAP[day.weekday()]

                if emp_sched:
                    sched = emp_sched.get(weekday)
                    if not sched:
                        continue                      # not a scheduled work day
                    start_t = sched.start_time or DEFAULT_START
                    end_t   = sched.end_time   or DEFAULT_END
                else:
                    if weekday == 'sun':
                        continue                      # no schedule → assume Sun off
                    start_t, end_t = DEFAULT_START, DEFAULT_END

                status = random.choices(
                    ['present', 'late', 'absent'],
                    weights=[PRESENT_WEIGHT, LATE_WEIGHT, ABSENT_WEIGHT],
                )[0]

                if status == 'absent':
                    clock_in = clock_out = None
                else:
                    if status == 'late':
                        clock_in = _shift(start_t, random.randint(8, 45))
                    else:
                        clock_in = _shift(start_t, random.randint(-12, 0))

                    # Today: some people are still on shift — leave clock_out empty.
                    if day == today and random.random() < 0.5:
                        clock_out = None
                    else:
                        clock_out = _shift(end_t, random.randint(-20, 35))
                        if clock_out <= clock_in:     # guard the check constraint
                            clock_out = _shift(clock_in, 480)

                to_create.append(Attendance(
                    user       = emp,
                    location   = emp.location,
                    qr_session = None,
                    date       = day,
                    status     = status,
                    clock_in   = clock_in,
                    clock_out  = clock_out,
                ))

        # ── Report ────────────────────────────────────────────────────────────
        counts = {'present': 0, 'late': 0, 'absent': 0}
        for a in to_create:
            counts[a.status] += 1

        self.stdout.write(
            f'Employees: {employees.count()} | '
            f'Range: {start_date} → {today} ({days} days)\n'
            f'To create: {len(to_create)}  '
            f'(present={counts["present"]}, late={counts["late"]}, absent={counts["absent"]})\n'
            f'Skipped (already had a record): {skipped}'
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('[dry-run] nothing written.'))
            return

        with transaction.atomic():
            Attendance.objects.bulk_create(to_create, batch_size=500)

        self.stdout.write(self.style.SUCCESS(f'Created {len(to_create)} attendance records.'))
