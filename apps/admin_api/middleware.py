import logging
import json

logger = logging.getLogger("api.errors")


class ErrorResponseLoggingMiddleware:
    """Logs request body + response body for any 4xx/5xx response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if response.status_code >= 400:
            try:
                request_body = request.body.decode("utf-8") or "-"
                # Try to pretty-print if JSON
                try:
                    request_body = json.dumps(json.loads(request_body), indent=2)
                except Exception:
                    pass
            except Exception:
                request_body = "-"

            try:
                response_body = response.content.decode("utf-8")
                try:
                    response_body = json.dumps(json.loads(response_body), indent=2)
                except Exception:
                    pass
            except Exception:
                response_body = "-"

            logger.warning(
                "\n[%s] %s %s\nRequest : %s\nResponse: %s",
                response.status_code,
                request.method,
                request.get_full_path(),
                request_body,
                response_body,
            )

        return response
