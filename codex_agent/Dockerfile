FROM ghcr.io/home-assistant/base:3.22

ARG BUILD_VERSION
ARG BUILD_ARCH
ARG CODEX_CLI_VERSION=0.139.0
ARG MARKITDOWN_VERSION=0.1.6
ARG UV_VERSION=0.11.23
ARG HA_MCP_VERSION=7.8.1

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
    ffmpeg \
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
RUN \
  /opt/codex-agent/bin/pip install --no-cache-dir -r /tmp/codex-agent-requirements.txt \
  && /opt/codex-agent/bin/pip install --no-cache-dir --no-deps "markitdown==${MARKITDOWN_VERSION}"

RUN \
  python3 -m venv /tmp/uv-bootstrap \
  && /tmp/uv-bootstrap/bin/pip install --no-cache-dir "uv==${UV_VERSION}" \
  && UV_PYTHON_INSTALL_DIR=/opt/ha-mcp/python \
    UV_TOOL_DIR=/opt/ha-mcp/tools \
    UV_TOOL_BIN_DIR=/opt/ha-mcp/bin \
    UV_LINK_MODE=copy \
    env -u UV_EXTRA_INDEX_URL -u PIP_EXTRA_INDEX_URL \
    /tmp/uv-bootstrap/bin/uv tool install --python 3.13 "ha-mcp==${HA_MCP_VERSION}" \
  && rm -rf /tmp/uv-bootstrap /root/.cache/uv

COPY run.sh /run.sh
COPY ha-mcp-stdio.sh /usr/local/bin/ha-mcp-stdio
COPY skills /opt/codex-agent-skills
COPY src /app/src

RUN chmod a+x /run.sh /usr/local/bin/ha-mcp-stdio

ENV PYTHONPATH=/app/src \
    CODEX_AGENT_DATA=/data \
    CODEX_AGENT_HOST=0.0.0.0 \
    CODEX_AGENT_PORT=8099

CMD ["/run.sh"]
