"""
Recurring-task engine.

The frontend sends a flat `recurrence` object:
    { "frequency": "weekly", "interval": 1, "weekdays": ["MO","WE","FR"], "day_of_month": null }

build_rrule()        → turns that into an iCalendar RRULE string (stored on the template).
expand_occurrences() → expands the rule from start_date forward (with day-31 / Feb-29 clamp).
generate_instances() → idempotently materializes Task rows (one per occurrence) + assignments.

A generated Task always gets its own due_date = the occurrence date, so every existing
status / overdue / performance code path keeps working unchanged.
"""

from datetime import date, timedelta
import calendar

from dateutil.rrule import rrule, DAILY, WEEKLY
from dateutil.relativedelta import relativedelta

# How far ahead we materialize Task rows at any time (the rolling window).
GENERATION_HORIZON_DAYS = 60

VALID_WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
_WD_TO_INT     = {wd: i for i, wd in enumerate(['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'])}


def build_rrule(recurrence):
    """recurrence dict → RRULE string. Assumes the dict already passed validation."""
    freq     = recurrence['frequency']
    interval = recurrence.get('interval') or 1

    if freq == 'daily':
        return f"FREQ=DAILY;INTERVAL={interval}"

    if freq == 'weekly':
        days = recurrence.get('weekdays') or []
        byday = ','.join([d for d in VALID_WEEKDAYS if d in days])
        return f"FREQ=WEEKLY;INTERVAL={interval};BYDAY={byday}"

    if freq == 'monthly':
        dom = recurrence.get('day_of_month')
        return f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY={dom}"

    if freq == 'yearly':
        return f"FREQ=YEARLY;INTERVAL={interval}"

    raise ValueError(f"Unsupported frequency: {freq}")


def _parse_rrule(rrule_str):
    """Tiny parser for the rules we emit (avoids depending on stored DTSTART)."""
    parts = {}
    for token in rrule_str.split(';'):
        if '=' in token:
            k, v = token.split('=', 1)
            parts[k] = v
    return parts


def _clamp_day(year, month, day):
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def expand_occurrences(rrule_str, start_date, until_date):
    """
    Return the list of occurrence dates from start_date..until_date (inclusive).

    Monthly/yearly are stepped with relativedelta and clamped to the last valid
    day (Jan-31 monthly → Feb-28; Feb-29 yearly → Feb-28 in non-leap years),
    instead of dateutil's default behaviour of skipping the month entirely.
    """
    p    = _parse_rrule(rrule_str)
    freq = p.get('FREQ')
    iv   = int(p.get('INTERVAL', 1))

    if freq == 'DAILY':
        return [d.date() for d in rrule(DAILY, interval=iv, dtstart=start_date, until=until_date)]

    if freq == 'WEEKLY':
        byday = [_WD_TO_INT[w] for w in p.get('BYDAY', '').split(',') if w in _WD_TO_INT]
        if not byday:
            byday = [start_date.weekday()]
        return [d.date() for d in rrule(WEEKLY, interval=iv, byweekday=byday,
                                        dtstart=start_date, until=until_date)]

    if freq == 'MONTHLY':
        dom = int(p.get('BYMONTHDAY', start_date.day))
        out = []
        cursor = date(start_date.year, start_date.month, 1)
        while cursor <= until_date:
            occ = _clamp_day(cursor.year, cursor.month, dom)
            if start_date <= occ <= until_date:
                out.append(occ)
            cursor += relativedelta(months=iv)
        return out

    if freq == 'YEARLY':
        out = []
        cursor = start_date
        while cursor <= until_date:
            occ = _clamp_day(cursor.year, start_date.month, start_date.day)
            if start_date <= occ <= until_date:
                out.append(occ)
            cursor += relativedelta(years=iv)
        return out

    return []


def generate_instances(template, horizon_days=GENERATION_HORIZON_DAYS, today=None):
    """
    Idempotently create Task rows for `template` within the rolling window
    [start_date .. max(today, start_date) + horizon_days]. Returns the list of
    Task objects that were newly created (ordered by due_date).

    Notifications are intentionally NOT sent here — the create view notifies once
    for the first instance; the rolling generator stays silent.
    """
    # Local imports to avoid circular import (models imports nothing from here).
    from .models import Task, TaskAssignment

    if not template.is_active:
        return []

    today      = today or date.today()
    window_end = max(today, template.start_date) + timedelta(days=horizon_days)

    occurrences = expand_occurrences(template.rrule, template.start_date, window_end)
    if not occurrences:
        # First occurrence is beyond the rolling window (e.g. a quarterly task whose
        # next date is >horizon away). Still materialize the first one so the task is
        # always visible and there's a representative instance to return/notify on.
        far = expand_occurrences(
            template.rrule, template.start_date,
            template.start_date + timedelta(days=3660),
        )
        occurrences = far[:1]
    if not occurrences:
        return []

    existing = set(
        Task.objects.filter(template=template, due_date__in=occurrences)
        .values_list('due_date', flat=True)
    )

    assignees    = list(template.assignees.all())
    freq         = _parse_rrule(template.rrule).get('FREQ', '').lower() or 'none'
    created_tasks = []

    for occ in occurrences:
        if occ in existing:
            continue
        task = Task.objects.create(
            template       = template,
            title          = template.title,
            description    = template.description,
            location       = template.location,
            created_by     = template.created_by,
            due_date       = occ,
            is_recurring   = True,
            frequency      = freq if freq in {'daily', 'weekly', 'monthly', 'yearly'} else 'none',
            requires_photo = template.requires_photo,
        )
        TaskAssignment.objects.bulk_create([
            TaskAssignment(task=task, employee=emp) for emp in assignees
        ])
        created_tasks.append(task)

    return created_tasks
