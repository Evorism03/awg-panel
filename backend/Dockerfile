FROM python:3.12-slim
WORKDIR /app
ARG DOCKER_CLI_VERSION=27.5.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends wireguard-tools sudo ca-certificates curl \
    && docker_arch="$(dpkg --print-architecture)" \
    && case "$docker_arch" in \
      amd64) docker_arch="x86_64" ;; \
      arm64) docker_arch="aarch64" ;; \
      armhf) docker_arch="armhf" ;; \
      *) echo "Unsupported Docker CLI architecture: $docker_arch" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${docker_arch}/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp docker/docker \
    && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz /var/lib/apt/lists/*
RUN command -v docker && docker --version
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
