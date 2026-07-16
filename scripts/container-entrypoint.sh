#!/bin/sh
# Docker Compose mounts file secrets as root-readable. Copy only the supported
# secret values to the private tmpfs, then drop to the service user. With all
# Linux capabilities removed, ownership cannot be changed; read-only mode is
# sufficient because this container has no other long-lived processes.
set -eu

copy_secret() {
    name="$1"
    eval "source_path=\${${name}_FILE:-}"
    [ -n "$source_path" ] || return 0
    destination="/tmp/${name}.secret"
    cat "$source_path" > "$destination"
    chmod 0444 "$destination"
    export "${name}_FILE=$destination"
}

copy_secret PIKVM_PASSWORD
copy_secret PIKVM_MCP_CONTROL_SECRET
copy_secret MCP_HTTP_BEARER_TOKEN

exec su-exec pikvm:pikvm pikvm-local-mcp "$@"
