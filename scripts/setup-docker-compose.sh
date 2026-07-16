#!/bin/sh
# Create a straightforward PiKVM MCP Docker Compose deployment.
# Download this script, inspect it, then run it locally. Do not pipe it to sh.
set -eu
umask 077

raw_base="${MCP_PIKVM_RAW_BASE:-https://raw.githubusercontent.com/rovingclimber/mcp-pikvm/${MCP_PIKVM_REF:-main}}"
target_dir="${MCP_PIKVM_DIR:-$PWD/mcp-pikvm}"

fail() { echo "Error: $*" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || fail "Install curl or wget first."
[ ! -e "$target_dir" ] || fail "Deployment directory already exists: $target_dir"

fetch() {
    source_path="$1"; destination="$2"; temporary="${destination}.tmp.$$"
    mkdir -p "$(dirname "$destination")"
    if command -v curl >/dev/null 2>&1; then
        curl --fail --silent --show-error --location "$raw_base/$source_path" --output "$temporary"
    else
        wget -qO "$temporary" "$raw_base/$source_path"
    fi
    mv "$temporary" "$destination"
}

prompt() {
    label="$1"; default="$2"
    printf '%s [%s]: ' "$label" "$default" >&2
    read -r value
    answer="${value:-$default}"
}

prompt_secret() {
    printf '%s: ' "$1" >&2
    [ ! -t 0 ] || stty -echo
    read -r value
    [ ! -t 0 ] || stty echo
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

safe_value() {
    case "$1" in ''|*"$(printf '\n')"*|*"$(printf '\r')"*) return 1 ;; *) return 0 ;; esac
}

env_quote() {
    # Docker Compose treats single-quoted dotenv values literally. Escape the
    # one special character so ordinary passwords may contain $, # and spaces.
    printf "'"
    printf '%s' "$1" | sed "s/'/\\\\'/g"
    printf "'"
}

mkdir -p "$target_dir"
fetch compose.yaml "$target_dir/compose.yaml"
fetch compose.https.yaml "$target_dir/compose.https.yaml"

echo "PiKVM MCP setup" >&2
echo "Your credentials will be kept in $target_dir/.env (not in Git)." >&2

printf 'Configure the PiKVM connection now? [Y/n]: ' >&2
read -r configure_now || configure_now=''
if [ "$configure_now" = n ] || [ "$configure_now" = N ]; then
    pikvm_url=''; pikvm_user=''; pikvm_password=''
else
    prompt 'PiKVM URL' 'https://192.168.1.50'; pikvm_url="$answer"
    prompt 'PiKVM username' 'admin'; pikvm_user="$answer"
    prompt_secret 'PiKVM password'; pikvm_password="$answer"
    [ -n "$pikvm_password" ] || fail "A PiKVM password is required."
fi

printf 'Use recommended HTTPS with Cloudflare DNS-01? [Y/n]: ' >&2
read -r use_https || use_https=''
if [ "$use_https" = n ] || [ "$use_https" = N ]; then
    prompt 'Trusted LAN hostname or IPv4 address' ''; lan_host="$answer"
    [ -n "$lan_host" ] || fail "A LAN hostname or address is required."
    bind_address='0.0.0.0'
    allowed_hosts="$lan_host:8000,localhost:8000,127.0.0.1:8000,[::1]:8000"
    public_host=''; acme_email=''; cf_token=''
    launch='docker compose up -d'
    endpoint="http://$lan_host:8000/mcp"
else
    prompt 'MCP public DNS name' 'mcp.example.com'; public_host="$answer"
    prompt 'Email for certificate renewal notices' ''; acme_email="$answer"
    prompt_secret 'Cloudflare API token (Zone Read + DNS Edit for this zone)'; cf_token="$answer"
    [ -n "$public_host" ] && [ -n "$acme_email" ] && [ -n "$cf_token" ] || fail "DNS name, email, and Cloudflare token are required for HTTPS."
    bind_address='127.0.0.1'
    allowed_hosts="$public_host,localhost:8000,127.0.0.1:8000,[::1]:8000"
    launch='docker compose -f compose.yaml -f compose.https.yaml up -d'
    endpoint="https://$public_host/mcp"
fi

bearer_token="$(random_secret)"
for value in "$pikvm_url" "$pikvm_user" "$pikvm_password" "$public_host" "$acme_email" "$cf_token" "$bearer_token"; do
    safe_value "$value" || fail "Values may not contain a line break."
done

cat > "$target_dir/.env" <<EOF
PIKVM_URL=$(env_quote "$pikvm_url")
PIKVM_USERNAME=$(env_quote "$pikvm_user")
PIKVM_PASSWORD=$(env_quote "$pikvm_password")
PIKVM_TLS_VERIFY=true
MCP_HTTP_BEARER_TOKEN=$(env_quote "$bearer_token")
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_STREAMABLE_HTTP_PATH=/mcp
MCP_BIND_ADDRESS=$bind_address
MCP_HTTP_ALLOWED_HOSTS=$(env_quote "$allowed_hosts")
MCP_HTTP_ALLOWED_ORIGINS=
MCP_PUBLIC_HOST=$(env_quote "$public_host")
ACME_EMAIL=$(env_quote "$acme_email")
CF_DNS_API_TOKEN=$(env_quote "$cf_token")
EOF
chmod 600 "$target_dir/.env"

echo '' >&2
echo "Created: $target_dir/.env" >&2
echo "MCP endpoint: $endpoint" >&2
echo "The persistent bearer token is in .env." >&2
echo "View and control tokens are deliberately generated at every container start; see docker compose logs pikvm-mcp." >&2
echo "Start it with:" >&2
echo "  cd $target_dir && $launch" >&2
