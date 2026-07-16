# syntax=docker/dockerfile:1
FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_STREAMABLE_HTTP_PATH=/mcp

RUN addgroup -S pikvm \
    && adduser -S -D -H -G pikvm pikvm

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
USER pikvm
EXPOSE 8000

# Streamable HTTP is the shareable-container default. Set MCP_TRANSPORT=stdio
# only when the container is launched by a local stdio MCP client.
CMD ["pikvm-local-mcp"]
