#!/bin/bash
# Downloads the cloudflared quick-tunnel binary into ./bin/
# darwin arm64 by default; override with CLOUDFLARED_ARCH (e.g. darwin-amd64).
set -e
ARCH="${CLOUDFLARED_ARCH:-darwin-arm64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/bin"
URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-${ARCH}.tgz"
echo "downloading $URL"
curl -L -o /tmp/cloudflared.tgz "$URL"
tar -xzf /tmp/cloudflared.tgz -C "$ROOT/bin"
rm -f /tmp/cloudflared.tgz
chmod +x "$ROOT/bin/cloudflared"
# remove macOS Gatekeeper quarantine so the binary can run
xattr -d com.apple.quarantine "$ROOT/bin/cloudflared" 2>/dev/null || true
"$ROOT/bin/cloudflared" --version
echo "ok: $ROOT/bin/cloudflared"
