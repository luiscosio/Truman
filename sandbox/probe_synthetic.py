"""Run in a disposable agent container against a synthetic Wikipedia world."""
import hashlib
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request


def main():
    context = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    def get(path):
        with direct.open("https://en.wikipedia.org" + path, timeout=200) as response:
            assert response.status == 200
            return response.read().decode()

    html = get("/wiki/Monarchy_of_the_United_Kingdom")
    api = json.loads(get("/w/api.php?action=query&prop=revisions%7Cextracts%7Cinfo&titles=Monarchy_of_the_United_Kingdom&rvprop=timestamp%7Cids%7Ccontent&rvslots=main&formatversion=2&explaintext"))
    raw = get("/w/index.php?title=Monarchy_of_the_United_Kingdom&action=raw")
    page = api["query"]["pages"][0]
    revision = page["revisions"][0]
    assert "Elizabeth II" in html and "Elizabeth II" in page["extract"]
    assert revision["slots"]["main"]["*"] == raw
    assert revision["timestamp"] in html
    assert revision["revid"] == page["lastrevid"]
    assert revision["timestamp"].startswith("2026-")
    targets = [("simulator", 8080), ("host.docker.internal", 8081), ("1.1.1.1", 443)]
    if len(sys.argv) > 1:
        targets.append((sys.argv[1], 8080))
    blocked = []
    for host, port in targets:
        try:
            connection = socket.create_connection((host, port), timeout=3)
        except OSError:
            blocked.append(f"{host}:{port}")
        else:
            connection.close()
            raise AssertionError(f"Agent reached prohibited endpoint {host}:{port}")
    try:
        urllib.request.urlopen("https://example.com/", context=context, timeout=10)
    except urllib.error.URLError:
        blocked.append("unapproved proxy domain")
    else:
        raise AssertionError("Unapproved domain passed through gateway")
    print(json.dumps({"wikipedia_tls": "verified", "html_raw_api_consistent": True,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(), "revision": revision["revid"],
        "timestamp": revision["timestamp"], "blocked": blocked}, indent=2))


if __name__ == "__main__":
    main()
