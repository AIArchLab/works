FROM python:3.11-slim
WORKDIR /app
COPY rb/ ./rb/
COPY config/ ./config/
COPY tests/ ./tests/
ENV RB_CONFIG=/app/config/tenants.json RB_KB=/app/config/kb.json RB_DB=/app/out/replybridge.db RB_PORT=8080
RUN mkdir -p /app/out
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')" || exit 1
CMD ["python3", "-m", "rb.server", "--port", "8080"]
