FROM python:3.12-slim-bookworm

ARG DENO_VERSION=2.1.4

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip" \
    -o /tmp/deno.zip \
    && apt-get update && apt-get install -y --no-install-recommends unzip \
    && unzip /tmp/deno.zip -d /usr/local/bin \
    && rm /tmp/deno.zip \
    && apt-get purge -y unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY templates ./templates
COPY static ./static

RUN pip install --no-cache-dir .

EXPOSE 8765

ENV DATA_DIR=/data
ENV OLLAMA_BASE_URL=http://ollama:11434

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]