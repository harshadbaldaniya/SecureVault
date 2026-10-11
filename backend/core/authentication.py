from rest_framework.authentication import SessionAuthentication as DRFSessionAuthentication


class SessionAuthentication(DRFSessionAuthentication):
    """DRF session auth that answers unauthenticated requests with 401 instead of 403.

    The SPA uses 401 to mean "log in again" and 403 to mean "logged in, but not allowed".
    CSRF enforcement for authenticated requests is inherited unchanged.
    """

    def authenticate_header(self, request):
        return 'Session realm="securevault"'
