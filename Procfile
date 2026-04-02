web: python manage.py migrate --noinput && python scripts/seed_django.py && gunicorn pms_portal.wsgi --bind 0.0.0.0:$PORT
