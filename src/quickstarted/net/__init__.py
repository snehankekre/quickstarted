"""Network policy: the harness-owned egress proxy."""

from .proxy import DEFAULT_NETWORK_ALLOW, EgressProxy, host_matches

__all__ = ["DEFAULT_NETWORK_ALLOW", "EgressProxy", "host_matches"]
