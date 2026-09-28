# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY packs ./packs
RUN uv build --wheel --out-dir /dist \
 && python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir "$(ls /dist/*.whl)[server]"

FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.title="DutyGate sidecar" \
      org.opencontainers.image.description="Flags legal and compliance triggers in inbound chatbot messages." \
      org.opencontainers.image.licenses="MIT"
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /opt/venv /opt/venv
COPY packs /packs
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"
ENTRYPOINT ["dutygate", "serve"]
CMD ["/packs/legal-triggers.yaml", "--host", "0.0.0.0", "--port", "8080"]
