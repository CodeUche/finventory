web: cd backend && gunicorn config.wsgi:application --config gunicorn.conf.py
worker: celery -A config.celery worker --loglevel=info --concurrency=2
beat: celery -A config.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
release: cd backend && python manage.py migrate --no-input && python manage.py collectstatic --no-input --clear
