"""
Helper for rendering a *collapsed* task list: recurring tasks show as ONE row
(their next upcoming occurrence) instead of one row per generated occurrence.
Shared by the super-admin, district-manager and branch-manager task lists.
"""

from rest_framework.pagination import PageNumberPagination
from django.utils import timezone

from .recurrence import representative_task_ids, series_meta, build_rrule, generate_instances


def collapsed_task_page(task_qs, request, serializer_class, page_size=15, extra_context=None):
    """
    Collapse `task_qs` to one row per recurring series (+ all one-time tasks),
    paginate, and return the paginated `.data` dict ({count,next,previous,results}).

    The serializer receives `series_meta` in context so recurring rows can show
    series-level aggregates (total_occurrences + status_counts across the series).
    """
    today      = timezone.localdate()
    rep_ids    = representative_task_ids(task_qs, today)
    collapsed  = task_qs.filter(id__in=rep_ids).order_by('-created_at')

    template_ids = list(
        collapsed.filter(template__isnull=False).values_list('template_id', flat=True)
    )
    meta = series_meta(template_ids, today)

    paginator           = PageNumberPagination()
    paginator.page_size = page_size
    page                = paginator.paginate_queryset(collapsed, request)

    context = {'series_meta': meta}
    if extra_context:
        context.update(extra_context)

    serializer = serializer_class(page, many=True, context=context)
    return paginator.get_paginated_response(serializer.data).data


def _notify_assigned(actor, task, emp, role_label):
    from .models import ActivityLog
    from apps.users.models import AppNotification
    ActivityLog.objects.create(
        action='task_assigned', actor=actor, task=task, target_user=emp,
        message=f'Task "{task.title}" assigned to {emp.get_full_name()}',
    )
    AppNotification.objects.create(
        recipient=emp, notif_type='task_assigned', title='New Task Assigned',
        message=f"{actor.get_full_name() or role_label} assigned you '{task.title}'", task=task,
    )


def update_task_or_template(task, vd, actor, role_label='Admin'):
    """
    Apply a validated TaskUpdateSerializer payload.

    - One-time task: update the single Task (existing behaviour).
    - Recurring task (task.template_id set): update the TEMPLATE, then delete and
      regenerate its future, not-yet-started occurrences so the changes (title,
      description, photo flag, recurrence pattern, start_date, added assignees)
      apply going forward. Past/today occurrences and any started work are kept.

    Returns the representative Task to serialize back to the client.
    """
    from .models import Task, TaskAssignment

    employees = vd.get('_employees')  # list[User] when assigned_to was provided

    # ── One-time task ─────────────────────────────────────────────
    if not task.template_id:
        for field in ['title', 'description', 'due_date', 'requires_photo']:
            if field in vd:
                setattr(task, field, vd[field])
        task.save()
        if employees:
            for emp in employees:
                _, created = TaskAssignment.objects.get_or_create(task=task, employee=emp)
                if created:
                    _notify_assigned(actor, task, emp, role_label)
        task.refresh_from_db()
        return task

    # ── Recurring task → update the template + regenerate future ──
    template = task.template
    if 'title' in vd:           template.title = vd['title']
    if 'description' in vd:      template.description = vd['description']
    if 'requires_photo' in vd:   template.requires_photo = vd['requires_photo']
    if vd.get('start_date'):     template.start_date = vd['start_date']
    if vd.get('recurrence'):     template.rrule = build_rrule(vd['recurrence'])
    template.save()

    if employees:
        for emp in employees:
            template.assignees.add(emp)

    today = timezone.localdate()
    # Keep occurrences that have already been acted on; delete the rest from today
    # forward and regenerate from the (possibly new) template.
    started_ids = set(
        Task.objects.filter(
            template=template, due_date__gte=today,
            assignments__status__in=['awaiting_review', 'approved', 'rejected', 'overdue'],
        ).values_list('id', flat=True)
    )
    Task.objects.filter(template=template, due_date__gte=today).exclude(id__in=started_ids).delete()
    generate_instances(template)

    rep = (
        Task.objects.filter(template=template, due_date__gte=today).order_by('due_date').first()
        or Task.objects.filter(template=template).order_by('-due_date').first()
    )
    return rep
