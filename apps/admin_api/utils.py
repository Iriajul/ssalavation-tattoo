from rest_framework.response import Response
from rest_framework import status

MAX_UPLOAD_MB = 20


def check_file_size(file, max_mb=MAX_UPLOAD_MB):
    """Return a 400 Response if file exceeds max_mb, otherwise None."""
    if file and file.size > max_mb * 1024 * 1024:
        return Response(
            {"error": f"File size must not exceed {max_mb} MB."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None
