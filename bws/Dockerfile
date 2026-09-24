FROM python:3.14-slim

ARG TARGETARCH
ARG BWS_VERSION=2.1.0

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl unzip jq ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN case "$TARGETARCH" in \
        amd64) BWS_ARCH="x86_64" ;; \
        arm64) BWS_ARCH="aarch64" ;; \
        *) echo "Unsupported architecture: $TARGETARCH"; exit 1 ;; \
    esac && \
    curl -L \
    "https://github.com/bitwarden/sdk/releases/download/bws-v${BWS_VERSION}/bws-${BWS_ARCH}-unknown-linux-gnu-${BWS_VERSION}.zip" \
    -o /tmp/bws.zip && \
    unzip /tmp/bws.zip -d /usr/local/bin && \
    chmod +x /usr/local/bin/bws && \
    rm /tmp/bws.zip

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]