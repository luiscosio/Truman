"""Operator-owned site classification, never a target-agent configuration."""
import copy
import re

CATEGORIES = ("altered", "unaltered", "blacklisted")
# Hosts served by a simulated world. Sealed profiles recorded before multi-site
# worlds call this transport "frozen-wikipedia"; both names mean the same.
WORLD_TRANSPORTS = ("world", "frozen-wikipedia")
# Compose service that serves every world-transport host (named before multi-site worlds).
ORIGIN = "wikipedia"


def validate(policy):
    if policy.get("schema_version") != 1 or policy.get("default") != "block":
        raise ValueError("Site policy must use schema 1 and default block")
    hosts = {}
    for category in CATEGORIES:
        for entry in policy[category]:
            if not entry.get("reason") or not entry.get("hosts"):
                raise ValueError("Every entry needs hosts and a reason")
            if category == "blacklisted" and entry.get("transport"):
                raise ValueError("Blacklisted sites cannot have an allowed transport")
            for host in entry["hosts"]:
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or ".." in host:
                    raise ValueError("Use exact lowercase DNS hostnames")
                if host in hosts:
                    raise ValueError("Overlapping site classifications: " + host)
                if category != "blacklisted" and entry.get("transport") not in (*WORLD_TRANSPORTS, "tls-passthrough"):
                    raise ValueError("Unsupported site transport")
                if category == "altered" and entry.get("transport") not in WORLD_TRANSPORTS:
                    raise ValueError("Altered sites require a world backend")
                hosts[host] = {**entry, "category": category}
    return hosts


def effective(policy, condition):
    result = copy.deepcopy(policy)
    validate(result)
    if condition == "reference":
        for entry in result["altered"]:
            entry["reason"] = "Authentic saved page text, rendered by the experiment; not the live site."
            result["unaltered"].append(entry)
        result["altered"] = []
    validate(result)
    return result
