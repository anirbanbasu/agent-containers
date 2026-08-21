#!/bin/bash
set -euo pipefail

# volume-bridge only ever serves inbound WebDAV reads from a local backend —
# it has no legitimate reason to make outbound connections, and the only
# thing that should ever be reachable inbound is that one WebDAV port — so
# this is a small, fixed, non-configurable deny-by-default policy rather than
# the shared agent-images/shared/egress-allowlist.sh: that script exists to
# support opening exceptions, and this image should never have any to open.
readonly webdav_port="${VOLUME_BRIDGE_LISTEN_ADDR:-0.0.0.0:16080}"
readonly webdav_tcp_port="${webdav_port##*:}"

iptables -P OUTPUT DROP
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
ip6tables -P OUTPUT DROP
ip6tables -A OUTPUT -o lo -j ACCEPT
ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

iptables -P INPUT DROP
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -p tcp --dport "$webdav_tcp_port" -m state --state NEW -j ACCEPT
ip6tables -P INPUT DROP
ip6tables -A INPUT -i lo -j ACCEPT
ip6tables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
ip6tables -A INPUT -p tcp --dport "$webdav_tcp_port" -m state --state NEW -j ACCEPT

exec gosu bridge /usr/local/lib/agent/volume-bridge-serve.sh
