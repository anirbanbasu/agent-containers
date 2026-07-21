#!/bin/bash
# Shared by agent-images/claude-code/entrypoint.sh and
# agent-images/agent-gateway/entrypoint.sh. Configures this container's own
# OUTPUT chain to allow only the hosts/IPs in AGENT_ALLOWED_EGRESS /
# /etc/agent/egress-allowlist.txt (file mount takes precedence over the env
# var), defaulting to deny-all when neither is set. Must be sourced and
# called as root, before any privilege drop, since it installs iptables
# rules and starts dnsmasq.

configure_egress_allowlist() {
    local allowlist_file="/etc/agent/egress-allowlist.txt"
    local ipset_name="agent_allowed"
    local ipset6_name="agent_allowed6"
    local -a allowlist

    # File mount takes precedence over the env var; neither set means deny-all.
    if [ -f "$allowlist_file" ]; then
        mapfile -t allowlist < <(grep -v '^\s*#' "$allowlist_file" | grep -v '^\s*$')
    elif [ -n "${AGENT_ALLOWED_EGRESS:-}" ]; then
        IFS=',' read -ra allowlist <<< "$AGENT_ALLOWED_EGRESS"
    else
        allowlist=()
    fi

    _egress_is_ipv4() { [[ "$1" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(/[0-9]{1,2})?$ ]]; }
    _egress_is_ipv6() { [[ "$1" == *:* ]]; }

    if [ "${#allowlist[@]}" -eq 1 ] && [ "${allowlist[0]}" = "*" ]; then
        echo "[egress-allowlist] AGENT_ALLOWED_EGRESS=* — no egress restrictions applied (IPv4 and IPv6)." >&2
        return 0
    fi

    if [ "${#allowlist[@]}" -eq 0 ]; then
        echo "[egress-allowlist] No allowlist configured (\$AGENT_ALLOWED_EGRESS unset, no $allowlist_file mount)." >&2
        echo "[egress-allowlist] Defaulting to deny-all outbound traffic (IPv4 and IPv6). Set AGENT_ALLOWED_EGRESS=host1,host2 (or '*' for unrestricted) to change this." >&2
        iptables -P OUTPUT DROP
        iptables -A OUTPUT -o lo -j ACCEPT
        iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
        ip6tables -P OUTPUT DROP
        ip6tables -A OUTPUT -o lo -j ACCEPT
        ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
        return 0
    fi

    echo "[egress-allowlist] Restricting egress to: ${allowlist[*]}" >&2

    # Preserve whatever resolvers were in place before we take over DNS.
    local upstream_dns
    upstream_dns=$(grep '^nameserver' /etc/resolv.conf | awk '{print $2}')

    ipset create "$ipset_name" hash:ip family inet -exist
    ipset create "$ipset6_name" hash:ip family inet6 -exist

    # /tmp rather than /etc: entrypoint runs before rootfs is guaranteed
    # writable (a --read-only container only gets /tmp and /run as tmpfs).
    local dnsmasq_conf=/tmp/dnsmasq.agent.conf
    {
        echo "no-resolv"
        echo "listen-address=127.0.0.1"
        echo "bind-interfaces"
        # Pin dnsmasq to a known, unprivileged UID so the NAT rules below can
        # tell its own upstream forwarding apart from every other process's
        # DNS traffic (both otherwise share the same destination: $upstream_dns).
        echo "user=dnsmasq"
        for ns in $upstream_dns; do
            echo "server=$ns"
        done
    } > "$dnsmasq_conf"

    local entry
    for entry in "${allowlist[@]}"; do
        entry="$(echo "$entry" | xargs)" # trim whitespace
        if _egress_is_ipv6 "$entry"; then
            ipset add "$ipset6_name" "$entry" -exist
        elif _egress_is_ipv4 "$entry"; then
            ipset add "$ipset_name" "$entry" -exist
        else
            # dnsmasq routes A records into the first set and AAAA records
            # into the second, based on each set's own address family.
            echo "ipset=/$entry/$ipset_name,$ipset6_name" >> "$dnsmasq_conf"
        fi
    done

    dnsmasq --conf-file="$dnsmasq_conf"

    iptables -P OUTPUT DROP
    iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT
    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    ip6tables -P OUTPUT DROP
    ip6tables -A OUTPUT -d ::1/128 -j ACCEPT
    ip6tables -A OUTPUT -o lo -j ACCEPT
    ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    for ns in $upstream_dns; do
        if _egress_is_ipv6 "$ns"; then
            ip6tables -A OUTPUT -p udp -d "$ns" --dport 53 -j ACCEPT
            ip6tables -A OUTPUT -p tcp -d "$ns" --dport 53 -j ACCEPT
        else
            iptables -A OUTPUT -p udp -d "$ns" --dport 53 -j ACCEPT
            iptables -A OUTPUT -p tcp -d "$ns" --dport 53 -j ACCEPT
        fi
    done
    iptables -A OUTPUT -m set --match-set "$ipset_name" dst -j ACCEPT
    ip6tables -A OUTPUT -m set --match-set "$ipset6_name" dst -j ACCEPT

    # Force every process's DNS traffic to the local filtering dnsmasq
    # instance via NAT instead of rewriting /etc/resolv.conf, which isn't
    # writable under --read-only. dnsmasq's own upstream forwarding (to the
    # same $upstream_dns) must not be redirected back to itself, so it's
    # excluded by UID via a negated owner match on the same rule, rather than
    # a separate RETURN rule ahead of a blanket REDIRECT — a plain append
    # (-A) here loses a race on Docker user-defined networks: Docker inserts
    # its own embedded-DNS NAT rule (destination 127.0.0.11) ahead of
    # whatever this script appends, and that rule is a terminating DNAT, so
    # a RETURN-then-REDIRECT pair appended afterward never even runs for
    # traffic to 127.0.0.11 — dnsmasq is silently bypassed, its ipset never
    # gets populated, and domain-based allowlist entries stay permanently
    # (and confusingly) blocked. Inserting (-I ... 1) a single rule with a
    # negated owner match wins that race: dnsmasq's own query still falls
    # through untouched to Docker's rule below it, while every other
    # process's query is redirected to the local dnsmasq before Docker's
    # rule ever sees it.
    iptables -t nat -I OUTPUT 1 -p tcp --dport 53 -m owner ! --uid-owner dnsmasq -j REDIRECT --to-ports 53
    iptables -t nat -I OUTPUT 1 -p udp --dport 53 -m owner ! --uid-owner dnsmasq -j REDIRECT --to-ports 53
    ip6tables -t nat -I OUTPUT 1 -p tcp --dport 53 -m owner ! --uid-owner dnsmasq -j REDIRECT --to-ports 53
    ip6tables -t nat -I OUTPUT 1 -p udp --dport 53 -m owner ! --uid-owner dnsmasq -j REDIRECT --to-ports 53
}
