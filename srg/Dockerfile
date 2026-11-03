# Rules + handoff + admin UI build (no model). Stdlib only. For the local-LLM build use Dockerfile.llm.
FROM python:3.10-slim
WORKDIR /app
COPY srg /app/srg
ENV PYTHONUNBUFFERED=1 PORT=8080
# SRG_CONFIG must point to a mounted/secret-provided config.json; admin_token required. The SQLite file is ephemeral in most container hosts: mount a volume before real use.
CMD ["python", "-m", "srg"]
