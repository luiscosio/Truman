"""Run inside the agent container before an experiment, with no model call."""
import json
import os
import socket
import ssl
import urllib.error
import urllib.request


def main():
    context = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    url = "https://en.wikipedia.org/wiki/Monarchy_of_the_United_Kingdom"
    with urllib.request.urlopen(url, context=context, timeout=10) as response:
        body = response.read().decode()
        assert response.status == 200
        assert "Elizabeth II" in body or "Charles III" in body
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    try:
        direct.open("https://1.1.1.1/", timeout=3)
    except (OSError, urllib.error.URLError):
        pass
    else:
        raise AssertionError("Direct external HTTPS is reachable")
    try:
        urllib.request.urlopen("https://example.com/", context=context, timeout=10)
    except urllib.error.URLError:
        pass
    else:
        raise AssertionError("Unapproved domain passed through gateway")
    try:
        urllib.request.urlopen("https://api.anthropic.com/", context=context, timeout=15)
    except urllib.error.HTTPError as exc:
        assert exc.code in (400, 401, 403, 404, 405), exc
        # A proxy denial is a tunnel exception, not an origin HTTP response.
    print(json.dumps({"wikipedia_ip": socket.gethostbyname("en.wikipedia.org"),
        "wikipedia_https": "verified", "direct_external_https": "blocked",
        "unapproved_proxy_domain": "blocked", "provider_tls": "reachable"}))


if __name__ == "__main__":
    main()
