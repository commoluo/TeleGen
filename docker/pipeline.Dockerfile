ARG BASE_IMAGE=python:3.12-bookworm
FROM ${BASE_IMAGE}

ARG OPENHANDS_PIP_SPEC=openhands==1.16.0
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG INSTALL_SYSTEM_DEPS=1
ARG PIP_INDEX_URL=

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONUNBUFFERED=1 \
    npm_config_loglevel=warn

COPY docker/openhands-constraints.txt /tmp/openhands-constraints.txt

RUN if [ "$INSTALL_SYSTEM_DEPS" = "1" ]; then \
        if [ -n "$APT_MIRROR" ]; then \
            rm -f /etc/apt/sources.list.d/debian.sources; \
            printf 'deb %s bookworm main\ndeb %s bookworm-updates main\ndeb %s bookworm-security main\n' "$APT_MIRROR" "$APT_MIRROR" "$APT_SECURITY_MIRROR" > /etc/apt/sources.list; \
        fi \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            ca-certificates \
            chromium \
            curl \
            docker.io \
            git \
            lsof \
            nodejs \
            npm \
            procps \
            unzip \
        && rm -rf /var/lib/apt/lists/*; \
    fi


RUN if [ -n "$PIP_INDEX_URL" ]; then python3 -m pip config set global.index-url "$PIP_INDEX_URL"; fi \
    && python3 -m pip install -c /tmp/openhands-constraints.txt "$OPENHANDS_PIP_SPEC" \
    && python3 -m pip install -c /tmp/openhands-constraints.txt \
        httpx \
        python-dotenv \
        selenium==4.15.2 \
        pillow==10.1.0

RUN python3 -m pip install -c /tmp/openhands-constraints.txt numpy

WORKDIR /workspace

CMD ["bash"]