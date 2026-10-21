FROM python:3.12-slim
WORKDIR /app
COPY taskloop/ taskloop/
RUN useradd --create-home worker && mkdir /data && chown worker /data
USER worker
VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "taskloop", "--db", "/data/tasks.sqlite3"]
CMD ["--help"]
