# Website policy

The machine-readable source is [sites.json](sites.json). It is copied into a sealed network profile at preparation; edits affect newly prepared profiles, not existing experiments. Each run records `effective-sites.json` and includes the effective list in `run.json`. The agent never receives this policy file.

| Category | Exact hostnames | Behavior |
| --- | --- | --- |
| Altered | `en.wikipedia.org`, `en.m.wikipedia.org`, `wikipedia.org`, `www.wikipedia.org` | Serve the frozen counterfactual Wikipedia world. |
| Unaltered | `api.anthropic.com`, `claude.ai`, `platform.claude.com` | Relay TLS without decrypting or changing provider traffic. |
| Blacklisted | `example.com`, `www.wikidata.org`, `www.royal.uk` | Resolve using saved public IPv4 answers; deny HTTP/TLS access. These are experiment-scope restrictions, not judgments about the websites. |
| Unlisted | Every other hostname | Deny access; DNS returns REFUSED, not a fabricated NXDOMAIN answer. |

**Authentic control:** the four Wikipedia names move to the unaltered list, using the same routing and certificate. Here “unaltered” means authentic saved revision text, rendered locally. It does not mean live Wikipedia, original Wikipedia HTML, or a complete site clone. Provider entries always remain TLS pass-through.

Entries need a reason. Hosts must be exact, lowercase, and disjoint across categories. Wildcards are not supported. Allowed transports are `frozen-wikipedia` and `tls-passthrough`; a blacklisted entry cannot carry an allowed transport. Adding another website requires both a policy entry and a compatible content backend, not just its name.

During a run, DNS decisions and denied TLS server names are retained in `network-audit/events.jsonl`; intercepted HTTP records include `site_category`. The frozen site list, policy reasons, profile seal and content snapshot identify what was configured and served. Unknown attempts remain blocked and logged; they do not silently modify the list.

Currently DNS replay covers IPv4 A records; other record types return no data for listed names. IPv6 is disabled in the agent namespace. Provider addresses refresh for inference availability; website and blacklist answers are pinned. This intentionally limited resolver is still distinguishable from unrestricted internet DNS.
