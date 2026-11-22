"""Clasificación cerrada de errores: nunca propagar texto libre del proveedor."""
def error_code(response):
    try:
        error = response.json().get('error', {})
        reasons = {e.get('reason') for e in error.get('errors', [])}
        reasons.update(e.get('reason') for e in error.get('details', []) if isinstance(e, dict))
    except (ValueError, AttributeError, TypeError):
        reasons = set()
    if response.status_code == 401:
        return 'AUTH_REQUIRED'
    if response.status_code == 403:
        if reasons & {'accessNotConfigured', 'SERVICE_DISABLED'}:
            return 'GMAIL_API_DISABLED'
        if reasons & {'dailyLimitExceeded', 'DAILY_LIMIT_EXCEEDED'}:
            return 'GMAIL_DAILY_QUOTA'
        if reasons & {'rateLimitExceeded', 'userRateLimitExceeded', 'RATE_LIMIT_EXCEEDED'}:
            return 'GMAIL_RATE_LIMIT'
        return 'GMAIL_PERMISSION_DENIED'
    if response.status_code == 429:
        return 'GMAIL_RATE_LIMIT'
    return 'HTTP_'+str(response.status_code)
