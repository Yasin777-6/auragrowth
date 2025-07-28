web: gunicorn rpgAi.wsgi:application --bind 0.0.0.0:$PORT --timeout 60 --keep-alive 2 --max-requests 1000 --max-requests-jitter 100 --workers 2
worker: celery -A rpgAi worker --loglevel=info --concurrency=2
