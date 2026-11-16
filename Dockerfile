# runtime: the harness, viewer and preparer. Standard library only.
FROM python:3.13.18-slim-trixie AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY truman /app/truman
COPY tests /app/tests
USER 10001:10001
ENTRYPOINT ["python", "-m", "truman"]
CMD ["--help"]

# test: the full harness suite, which also imports the world engine and the
# trace-video tool. Versions match the rewrite and video extras in pyproject.toml.
FROM runtime AS test
USER root
RUN pip install --no-cache-dir mwparserfromhell==0.7.2 lxml==6.1.3 pyyaml==6.0.3 pillow==13.0.0
COPY sandbox /app/sandbox
COPY tools/trace-video /app/tools/trace-video
USER 10001:10001
CMD ["test"]

# The default target stays the dependency-free runtime.
FROM runtime
