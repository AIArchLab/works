FROM python:3.12-slim
WORKDIR /app
COPY app.py /app/app.py
COPY static /app/static
RUN useradd --uid 10001 --create-home appuser && mkdir /app/data && chown appuser:appuser /app/data
USER appuser
EXPOSE 8080
CMD ["python","app.py","--host","0.0.0.0"]
