import time
from django.core.cache import cache
from django.http import HttpResponse
from django.contrib.auth import logout

class DynamicConfigurationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        maintenance_mode = cache.get('maintenance_mode', False)
        if maintenance_mode and not request.path.startswith('/custom-admin') and not request.path.startswith('/login'):
            if not request.user.is_authenticated or not request.user.is_staff:
                return HttpResponse(
                    "<div style='font-family: sans-serif; text-align: center; padding-top: 100px;'>"
                    "<h1>🛠️ System Under Maintenance</h1>"
                    "<p>We are currently updating the Smart CRM. Please check back shortly.</p>"
                    "</div>", 
                    status=503
                )

        max_mb = int(cache.get('max_upload_size', 5))
        if request.method == 'POST' and request.META.get('CONTENT_LENGTH'):
            if int(request.META['CONTENT_LENGTH']) > (max_mb * 1024 * 1024):
                return HttpResponse(f"Payload Too Large. Maximum allowed size is {max_mb}MB.", status=413)

        if request.user.is_authenticated:
            timeout_mins = int(cache.get('session_timeout', 120))
            last_activity = request.session.get('last_activity')
            now = time.time()

            if last_activity and (now - last_activity) > (timeout_mins * 60):
                logout(request)
            else:
                request.session['last_activity'] = now

        return self.get_response(request)