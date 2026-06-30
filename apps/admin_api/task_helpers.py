"""
Helper for rendering a *collapsed* task list: recurring tasks show as ONE row
(their next upcoming occurrence) instead of one row per generated occurrence.
Shared by the super-admin, district-manager and branch-manager task lists.
"""

from rest_framework.pagination import PageNumberPagination
from django.utils import timezone

from .recurrence import representative_task_ids, series_meta


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
