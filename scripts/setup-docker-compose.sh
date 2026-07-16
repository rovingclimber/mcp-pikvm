#!/bin/sh
# Create a private Docker Compose deployment without putting credentials in Git.
# Download this script, inspect it, then run it locally. Do not pipe it to sh.
set -eu
umask 077

raw_base="${MCP_PIKVM_RAW_BASE:-https://raw.githubusercontent.com/rovingclimber/mcp-pikvm/${MCP_PIKVM_REF:-main}}"
target_dir="${MCP_PIKVM_DIR:-$PWD/mcp-pikvm}"

fail() {
    echo "Error: $*" >&2
    exit 1
}

command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || fail "Install curl or wget first."

if [ -e "$target_dir" ] && [ -n "$(ls -A "$target_dir" 2>/dev/null || true)" ]; then
    fail "Deployment directory already exists and is not empty: $target_dir"
fi

fetch() {
    source_path="$1"
    destination="$2"
    temporary="${destination}.tmp.$$"
    mkdir -p "$(dirname "$destination")"
    if command -v curl >/dev/null 2>&1; then
        curl --fail --silent --show-error --location "$raw_base/$source_path" --output "$temporary"
    else
        wget -qO "$temporary" "$raw_base/$source_path"
    fi
    mv "$temporary" "$destination"
}

prompt() {
    label="$1"
    default="$2"
    printf '%s [%s]: ' "$label" "$default" >&2
    read -r value
    answer="${value:-$default}"
}

prompt_secret() {
    label="$1"
    printf '%s: ' "$label" >&2
    if [ -t 0 ]; then
        stty -echo
    fi
    read -r value
    if [ -t 0 ]; then
        stty echo
    fi
    printf '\n' >&2
    answer="$value"
}

random_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 32 | tr -d '\n'
    else
        dd if=/dev/urandom bs=32 count=1 2>/dev/null | base64 | tr -d '\n'
    fi
}

safe_line() {
    case "$1" in
        ''|*' '*|*"$(printf '\t')"*|*'#'*|*'$'*) return 1 ;;
        *) return 0 ;;
    esac
}

safe_host() {
    case "$1" in
        ''|*[!A-Za-z0-9.-]*|.*|*.) return 1 ;;
        *) return 0 ;;
    esac
}

mkdir -p "$target_dir/secrets" "$target_dir/deploy"
fetch compose.yaml "$target_dir/compose.yaml"
fetch compose.https.yaml "$target_dir/compose.https.yaml"
fetch deploy/Caddyfile "$target_dir/deploy/Caddyfile"

echo "PiKVM MCP deployment setup" >&2
echo "Secrets will be saved under $target_dir/secrets with owner-only permissions." >&2

prompt 'PiKVM URL' 'https://192.168.1.50'
pikvm_url="$answer"
safe_line "$pikvm_url" || fail "PiKVM URL contains unsupported characters."
prompt 'PiKVM username' 'admin'
username="$answer"
safe_line "$username" || fail "PiKVM username contains unsupported characters."
prompt_secret 'PiKVM password'
password="$answer"
[ -n "$password" ] || fail "A PiKVM password is required."

printf 'Enable screen capture for this MCP server? [y/N]: ' >&2
read -r enable_screen
case "$enable_screen" in
    y|Y|yes|YES) screen_capture=1 ;;
    *) screen_capture=0 ;;
esac

printf 'Use Caddy automatic HTTPS for a public DNS name? [y/N]: ' >&2
read -r use_https
case "$use_https" in
    y|Y|yes|YES)
        prompt 'Public DNS name (for example mcp.example.com)' ''
        public_host="$answer"
        safe_host "$public_host" || fail "Enter a plain public DNS name, without a scheme, port, or path."
        allowed_hosts="$public_host"
        launch_command='docker compose -f compose.yaml -f compose.https.yaml up -d'
        public_host_line="MCP_PUBLIC_HOST=$public_host"
        ;;
    *)
        allowed_hosts='localhost:8000,127.0.0.1:8000,[::1]:8000'
        launch_command='docker compose up -d'
        public_host_line='# MCP_PUBLIC_HOST is only required with compose.https.yaml'
        ;;
esac

control_secret="$(random_secret)"
bearer_token="$(random_secret)"

cat > "$target_dir/secrets/pikvm-mcp.env" <<EOF
# Created locally by setup-docker-compose.sh. This file has no secret values.
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_STREAMABLE_HTTP_PATH=/mcp
MCP_HTTP_ALLOWED_HOSTS=$allowed_hosts
MCP_HTTP_ALLOWED_ORIGINS=
$public_host_line
PIKVM_URL=$pikvm_url
PIKVM_ALLOW_PRIVATE_HOSTNAMES=1
PIKVM_USERNAME=$username
PIKVM_TLS_VERIFY=true
PIKVM_MCP_CONTROL_TTL_SECONDS=300
PIKVM_MCP_SCREEN_CAPTURE_ENABLED=$screen_capture
PIKVM_MCP_SCREENSHOT_TTL_SECONDS=30
EOF
printf '%s\n' "$password" > "$target_dir/secrets/pikvm_password.txt"
printf '%s\n' "$control_secret" > "$target_dir/secrets/pikvm_control_secret.txt"
printf '%s\n' "$bearer_token" > "$target_dir/secrets/mcp_http_bearer_token.txt"
chmod 700 "$target_dir/secrets"
chmod 600 "$target_dir/secrets/pikvm-mcp.env" "$target_dir/secrets"/*.txt

echo '' >&2
echo "Configuration created in: $target_dir" >&2
echo "The bearer token is in secrets/mcp_http_bearer_token.txt." >&2
echo "The separate control secret is in secrets/pikvm_control_secret.txt." >&2
if [ "$use_https" = y ] || [ "$use_https" = Y ] || [ "$use_https" = yes ] || [ "$use_https" = YES ]; then
    echo "Before starting: point $public_host at this server and allow inbound TCP 80 and 443." >&2
fi
echo "Start it with:" >&2
echo "  cd $target_dir && $launch_command" >&2
