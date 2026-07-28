FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        unzip \
        jq \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN curl -L \
    https://github.com/bitwarden/sdk/releases/download/bws-v2.1.0/bws-aarch64-unknown-linux-gnu-2.1.0.zip \
    -o /tmp/bws.zip && \
    unzip /tmp/bws.zip -d /usr/local/bin && \
    chmod +x /usr/local/bin/bws && \
    rm /tmp/bws.zip

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]