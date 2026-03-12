web: cd backend && gunicorn config.wsgi:application --config gunicorn.conf.py
worker: cd backend && celery -A config.celery worker --loglevel=info --concurrency=4
beat: cd backend && celery -A config.celery beat --loglevel=info
release: cd backend && python manage.py migrate --no-input && python manage.py collectstatic --no-input --clear
