"""
Regression test for the health-check-gets-throttled bug.

Symptom on AWS: the ALB target group for the ECS `api` service never went
healthy. `HealthCheckView` (GET /api/v1/health/) is a plain APIView with no
throttle override, so it inherited the default anonymous throttle —
60/hour (see DEFAULT_THROTTLE_RATES in config/settings/base.py, tightened
further in production.py). The ALB polls the health endpoint every 15-30s
(120-240 req/hour), blows past 60/hour within the first ~15-30 minutes, and
every probe after that gets a 429 — the load balancer's own health check was
what triggered the "unhealthy" verdict, not any real app problem. A manual
curl looked fine because it landed outside the already-exhausted window,
which is what made this easy to miss.

Fix: HealthCheckView now sets `throttle_classes = []`, exempting it from
rate limiting entirely — standard practice for a load-balancer health probe.

This test would have caught the bug: it hits the health endpoint well past
60 times from a single client (no auth, matching how the ALB calls it) and
asserts none of the responses are 429. Uses a real cache backend
(LocMemCache) instead of the test suite's default DummyCache, because
AnonRateThrottle tracks request history via the cache — under DummyCache
every get() returns None and throttling silently never engages, which would
make this test pass regardless of whether the fix is present.
"""
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

# Deliberately below production's 60/hour anon rate so the loop below (65
# requests) would trip it if this endpoint were throttled at all.
_THROTTLED_RATES = {
    "anon": "60/hour",
    "user": "1000/hour",
}


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class HealthCheckThrottlingTests(TestCase):
    """GET /api/v1/health/ must never be rate-limited — load balancers and
    uptime monitors poll it far more often than any real-traffic quota."""

    def setUp(self):
        # Isolate this test's throttle counters from anything else that may
        # have touched the cache (LocMemCache is process-wide, not per-test).
        cache.clear()
        self.client = APIClient()
        self.url = reverse("health-check")

    def _rates_with_anon_throttle(self):
        from rest_framework.settings import api_settings
        original = dict(api_settings.DEFAULT_THROTTLE_RATES)
        original.update(_THROTTLED_RATES)
        return original

    def test_survives_far_more_requests_than_the_anon_rate_limit(self):
        from rest_framework.settings import api_settings

        original_rates = api_settings.DEFAULT_THROTTLE_RATES
        api_settings.DEFAULT_THROTTLE_RATES = self._rates_with_anon_throttle()
        try:
            statuses = []
            # 65 requests from one client, no auth — same shape as an ALB
            # probing every 15-30s: same "IP", never authenticated. 65 is
            # comfortably past the 60/hour anon limit that used to apply.
            for _ in range(65):
                response = self.client.get(self.url)
                statuses.append(response.status_code)

            self.assertNotIn(
                429, statuses,
                "health check was throttled — a load balancer polling this "
                "endpoint would see 429s and mark the target unhealthy",
            )
            # Every response should be a real health verdict (200 ok, or 503
            # if DB/cache checks fail in this environment) — never anything
            # throttling-shaped.
            self.assertTrue(all(s in (200, 503) for s in statuses), statuses)
        finally:
            api_settings.DEFAULT_THROTTLE_RATES = original_rates

    def test_response_carries_no_throttle_headers(self):
        """Belt-and-suspenders: confirm no throttle class is attached at all,
        not just that the default rate happens not to trip."""
        from apps.core.views import HealthCheckView
        self.assertEqual(
            HealthCheckView.throttle_classes, [],
            "HealthCheckView must not inherit DEFAULT_THROTTLE_CLASSES",
        )
