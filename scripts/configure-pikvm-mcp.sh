#!/bin/sh
# Interactive, local-only setup for the PiKVM MCP runtime environment.
set -eu
umask 077

config_dir="${HOME}/.config"
env_file="${PIKVM_MCP_ENV_FILE:-${config_dir}/pikvm-local-mcp.env}"
tmp_file="${env_file}.tmp.$$"

cleanup() {
    stty echo 2>/dev/null || true
    rm -f "$tmp_file"
}
trap cleanup EXIT HUP INT TERM

if [ -f "$env_file" ]; then
    current_url=$(sed -n 's/^PIKVM_URL=//p' "$env_file" | tail -n 1)
else
    current_url="https://kvm-pi-2.rovingclimber.com"
fi

printf 'PiKVM URL [%s]: ' "$current_url"
read -r url
url=${url:-$current_url}

printf 'PiKVM username: '
read -r username
[ -n "$username" ] || { echo "A PiKVM username is required." >&2; exit 1; }

printf 'PiKVM password: '
stty -echo
read -r password
stty echo
printf '\n'
[ -n "$password" ] || { echo "A PiKVM password is required." >&2; exit 1; }

printf 'Control secret (leave blank to generate one): '
stty -echo
read -r control_secret
stty echo
printf '\n'

generated_secret=false
if [ -z "$control_secret" ]; then
    control_secret=$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | base64 | tr -d '\n')
    generated_secret=true
fi

mkdir -p "$config_dir"
cat > "$tmp_file" <<EOF
# Generated locally by configure-pikvm-mcp.sh. Never commit or share this file.
PIKVM_URL=$url
PIKVM_ALLOW_PRIVATE_HOSTNAMES=1
PIKVM_USERNAME=$username
PIKVM_PASSWORD=$password
PIKVM_TLS_VERIFY=true
PIKVM_MCP_CONTROL_SECRET=$control_secret
PIKVM_MCP_CONTROL_TTL_SECONDS=300
PIKVM_MCP_SCREEN_CAPTURE_ENABLED=1
PIKVM_MCP_SCREENSHOT_TTL_SECONDS=30
EOF
chmod 0600 "$tmp_file"
mv "$tmp_file" "$env_file"

echo "Saved protected runtime configuration to: $env_file"
if [ "$generated_secret" = true ]; then
    echo ""
    echo "Generated control secret (store this in your password manager):"
    echo "$control_secret"
    echo "You must deliberately provide it to pikvm_enable_control before any control action."
fi
