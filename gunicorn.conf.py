import os

port = os.environ.get("PORT", "10000")
bind = f"0.0.0.0:{port}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = int(os.environ.get("WEB_TIMEOUT", "120"))
keepalive = 5
accesslog = "-"
errorlog = "-"
