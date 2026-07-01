"""
Load CELERY_BEAT_SCHEDULE from settings into the django_celery_beat DB tables.

Idempotent — safe to run on every deploy. Creates missing tasks, updates
existing ones if the schedule changed. Never deletes tasks it didn't create.

Usage:
    python manage.py setup_periodic_tasks
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sync CELERY_BEAT_SCHEDULE from settings into the PeriodicTask database."

    def handle(self, *args, **options):
        from celery.schedules import crontab
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        schedule_config = getattr(settings, "CELERY_BEAT_SCHEDULE", {})
        if not schedule_config:
            self.stdout.write(self.style.WARNING("CELERY_BEAT_SCHEDULE is empty — nothing to sync."))
            return

        created_count = 0
        updated_count = 0

        for name, config in schedule_config.items():
            task_name = config["task"]
            raw_schedule = config["schedule"]

            if not isinstance(raw_schedule, crontab):
                self.stdout.write(
                    self.style.WARNING(f"  Skipping '{name}': only crontab schedules are supported.")
                )
                continue

            # Parse crontab fields — celery stores them as strings
            minute = str(raw_schedule._orig_minute)
            hour = str(raw_schedule._orig_hour)
            day_of_week = str(raw_schedule._orig_day_of_week)
            day_of_month = str(raw_schedule._orig_day_of_month)
            month_of_year = str(raw_schedule._orig_month_of_year)

            cron, _ = CrontabSchedule.objects.get_or_create(
                minute=minute,
                hour=hour,
                day_of_week=day_of_week,
                day_of_month=day_of_month,
                month_of_year=month_of_year,
                timezone=settings.TIME_ZONE,
            )

            kwargs = config.get("kwargs", {})
            args_list = config.get("args", [])

            task, created = PeriodicTask.objects.update_or_create(
                name=name,
                defaults={
                    "task": task_name,
                    "crontab": cron,
                    "args": json.dumps(args_list),
                    "kwargs": json.dumps(kwargs),
                    "enabled": True,
                },
            )

            if created:
                created_count += 1
                self.stdout.write(f"  Created  '{name}' -> {task_name}")
            else:
                updated_count += 1
                self.stdout.write(f"  Updated  '{name}' -> {task_name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. {created_count} task(s) created, {updated_count} task(s) updated."
            )
        )
