FROM python:3.13-alpine3.24
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY truman /app/truman
COPY tests /app/tests
USER 10001:10001
ENTRYPOINT ["python", "-m", "truman"]
CMD ["--help"]
