FROM ghcr.io/home-assistant/base:3.22

ARG BUILD_VERSION
ARG BUILD_ARCH
ARG CODEX_CLI_VERSION=0.139.0

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.title="Home Assistant Codex Agent" \
  org.opencontainers.image.description="Sidebar Codex agent for Home Assistant administrators" \
  org.opencontainers.image.source="https://github.com/SeerKan/hassio-codex-addon" \
  org.opencontainers.image.licenses="MIT"

RUN \
  apk add --no-cache \
    bash \
    ca-certificates \
    curl \
    diffutils \
    git \
    jq \
    nodejs \
    npm \
    openssh-client \
    patch \
    py3-pip \
    python3 \
    ripgrep \
    tini \
  && npm install -g "@openai/codex@${CODEX_CLI_VERSION}" \
  && python3 -m venv /opt/codex-agent \
  && /opt/codex-agent/bin/pip install --no-cache-dir --upgrade pip

COPY requirements.txt /tmp/codex-agent-requirements.txt
RUN /opt/codex-agent/bin/pip install --no-cache-dir -r /tmp/codex-agent-requirements.txt

COPY run.sh /run.sh
COPY src /app/src

RUN chmod a+x /run.sh

ENV PYTHONPATH=/app/src \
    CODEX_AGENT_DATA=/data \
    CODEX_AGENT_HOST=0.0.0.0 \
    CODEX_AGENT_PORT=8099

CMD ["/run.sh"]
