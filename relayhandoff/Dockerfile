FROM python:3.12-slim
WORKDIR /app
COPY server.py dashboard.html ./
COPY sdk/ ./sdk/
RUN mkdir /data && chown -R 65532:65532 /data /app
USER 65532:65532
EXPOSE 8787
VOLUME ["/data"]
CMD ["python", "server.py", "--host", "0.0.0.0", "--db", "/data/state.db"]
