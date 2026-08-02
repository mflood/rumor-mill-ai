release: alembic upgrade head
web: uvicorn rumor_mill.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"
worker: python -m rumor_mill.worker
