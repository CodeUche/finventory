"""
Celery application configuration.

Import this in config/__init__.py to ensure tasks are discovered.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("finventory")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Test task to verify Celery is running."""
    print(f"Request: {self.request!r}")
