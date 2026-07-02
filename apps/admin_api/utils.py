from rest_framework.response import Response
from rest_framework import status

MAX_UPLOAD_MB = 20


_PERIOD_ALIASES = {
    'week': 'weekly', 'wk': 'weekly',
    'month': 'monthly', 'mo': 'monthly',
    'year': 'yearly', 'yr': 'yearly',
    'day': 'today', 'daily': 'today',
}


def normalize_period(value, default='weekly'):
    """
    Normalize a `period` query param so casing/format doesn't matter:
    'Weekly', 'WEEKLY', 'week' → 'weekly'; 'Monthly' → 'monthly'; etc.
    Unknown values (e.g. 'today', 'all', 'none') pass through lowercased.
    """
    if not value:
        return default
    v = str(value).strip().lower()
    return _PERIOD_ALIASES.get(v, v)


def check_file_size(file, max_mb=MAX_UPLOAD_MB):
    """Return a 400 Response if file exceeds max_mb, otherwise None."""
    if file and file.size > max_mb * 1024 * 1024:
        return Response(
            {"error": f"File size must not exceed {max_mb} MB."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None
