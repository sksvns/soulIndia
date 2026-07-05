import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse


def health(request):
    checks = {}
    healthy = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        healthy = False
        checks["database"] = f"error: {exc}"

    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        client.ping()
        checks["redis"] = "ok"
        checks["broker"] = "ok"
    except Exception as exc:
        healthy = False
        checks["redis"] = f"error: {exc}"
        checks["broker"] = f"error: {exc}"

    status_code = 200 if healthy else 503
    return JsonResponse({"status": "ok" if healthy else "error", **checks}, status=status_code)
