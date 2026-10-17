FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user

RUN useradd --create-home --uid 1000 user
WORKDIR /app
COPY requirements-space-lock.txt /app/
RUN pip install --no-cache-dir -r requirements-space-lock.txt

COPY --chown=user:user pyproject.toml README.md /app/
COPY --chown=user:user src /app/src
COPY --chown=user:user config /app/config
COPY --chown=user:user data/procedures.json /app/data/procedures.json
COPY --chown=user:user harbor_simulation /app/harbor_simulation
COPY --chown=user:user simulator /app/simulator
COPY --chown=user:user scripts /app/scripts
RUN pip install --no-deps --no-build-isolation . && mkdir -p /app/runtime && chown user:user /app/runtime

USER user
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/_stcore/health', timeout=2); urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"
CMD ["python", "-m", "scripts.launch_space"]
