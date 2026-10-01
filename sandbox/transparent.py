"""Host preparation and preflight for the transparent experiment network."""
import argparse
import datetime as dt
import ipaddress
import json
import random
import socket
import subprocess
from pathlib import Path

from sandbox.archive import durable, encoded, journal, seal, sha, verify

ROOT = Path(__file__).resolve().parent.parent
WIKI = ("en.wikipedia.org", "en.m.wikipedia.org", "wikipedia.org", "www.wikipedia.org")


def image_id(name):
    return subprocess.check_output(["docker", "image", "inspect", name, "--format", "{{.Id}}"], text=True).strip()


def prepare(path, managed=False, policy_path=None):
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    for name in ("tls", "trust"):
        (path / name).mkdir()
    names, served = WIKI, WIKI
    if managed:
        from sandbox.site_policy import WORLD_TRANSPORTS, validate
        policy = json.loads(policy_path.read_bytes())
        names = validate(policy)
        served = tuple(host for host, entry in names.items() if entry.get("transport") in WORLD_TRANSPORTS)
        durable(path / "sites.json", encoded(policy))
    answers = {name: sorted({v[4][0] for v in socket.getaddrinfo(name, 443, socket.AF_INET, socket.SOCK_STREAM)}) for name in names}
    if any(not ipaddress.ip_address(ip).is_global for ips in answers.values() for ip in ips):
        raise ValueError("Expected public IPv4 answers for every listed host")
    durable(path / "dns.json", encoded({"captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "Host system DNS at preparation; pinned for replay", "answers": answers}))
    renderer, base_agent = image_id("truman-network-world:local"), image_id("truman-network-agent:local")
    base_tag = "truman-agent-base:" + base_agent.split(":")[1][:16]
    subprocess.run(["docker", "tag", base_agent, base_tag], check=True)
    with (path / "certificate-setup.log").open("xb") as log:
        subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", str(path / "tls") + ":/tls",
            "-v", str(path / "trust") + ":/trust",
            "-v", str(ROOT / "sandbox/certificates.sh") + ":/certificate-setup.sh:ro",
            "-e", "TRUMAN_CA_NAME=" + ("Managed Network Root CA" if managed else "Sandbox Local CA"),
            "-e", "TRUMAN_SERVER_NAMES=" + ",".join(served), renderer, "sh", "-c",
            "sh /certificate-setup.sh && chmod 644 /tls/server.key"], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=60)
    tag = "truman-managed-agent:local" if managed else "truman-transparent-agent:local"
    with (path / "agent-build.log").open("xb") as log:
        subprocess.run(["docker", "build", "-f", "sandbox/Dockerfile.managed-agent" if managed else "sandbox/Dockerfile.transparent-agent",
            "--build-arg", "BASE_AGENT=" + base_tag, "--build-context", "trust=" + str(path / "trust"),
            "-t", tag, "."], cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=300)
    durable(path / "profile.json", encoded({"agent_image": image_id(tag), "engine": "managed" if managed else "transparent",
        "base_agent_image": base_agent, "ca_sha256": sha((path / "trust/ca.crt").read_bytes()),
        "dns_sha256": sha((path / "dns.json").read_bytes())}))
    print("Profile seal: " + seal(path), flush=True)


def configure(folder, world, profile, env):
    verify(profile)
    profile_data = json.loads((profile / "profile.json").read_bytes())
    image_id(profile_data["agent_image"])
    managed = profile_data.get("engine") == "managed"
    gateway = image_id("truman-managed-gateway:local" if managed else "truman-transparent-gateway:local")
    env.update(TRUMAN_AGENT_IMAGE=profile_data["agent_image"], TRUMAN_GATEWAY_IMAGE=gateway,
               TRUMAN_GATEWAY_ENGINE="managed" if managed else "transparent")
    if managed:
        from sandbox.site_policy import effective
        durable(folder / "effective-sites.json", encoded(effective(json.loads((profile / "sites.json").read_bytes()), world.condition)))
        env["TRUMAN_SITES_FILE"] = str((folder / "effective-sites.json").resolve())
    occupied = []
    ids = subprocess.check_output(["docker", "network", "ls", "-q"], text=True).split()
    for network in json.loads(subprocess.check_output(["docker", "network", "inspect", *ids], text=True)) if ids else []:
        occupied += [ipaddress.ip_network(c["Subnet"]) for c in (network.get("IPAM", {}).get("Config") or []) if c.get("Subnet")]
    choices = list(range(1, 250))
    random.SystemRandom().shuffle(choices)
    subnet = next((ipaddress.ip_network(f"172.30.{n}.0/24") for n in choices
                   if not any(ipaddress.ip_network(f"172.30.{n}.0/24").overlaps(x) for x in occupied if x.version == 4)), None)
    if subnet is None:
        raise ValueError("No unused experiment subnet available")
    router, client = str(subnet[2]), str(subnet[3])
    for name in ("origin-capture", "network-audit"):
        (folder / name).mkdir()
    durable(folder / "resolv.conf", f"nameserver {router}\noptions timeout:2 attempts:2\n".encode())
    env.update(TRUMAN_PROFILE_DIR=str(profile.resolve()), TRUMAN_RENDERER_IMAGE=world.snapshot["renderer_image"],
        TRUMAN_EDGE_SUBNET=str(subnet), TRUMAN_ROUTER_IP=router, TRUMAN_CLIENT_IP=client,
        TRUMAN_ORIGIN_CAPTURE_DIR=str((folder / "origin-capture").resolve()),
        TRUMAN_NETWORK_AUDIT_DIR=str((folder / "network-audit").resolve()),
        TRUMAN_RESOLV_CONF=str((folder / "resolv.conf").resolve()))
    durable(folder / "network-profile.json", encoded({**profile_data, "profile_seal": verify(profile),
        "dns": json.loads((profile / "dns.json").read_bytes()), "edge_subnet": str(subnet),
        "gateway_image": gateway}))


PROBE = r'''
import hashlib,http.client,json,os,socket,ssl,sys
from pathlib import Path
clues={k:v for k,v in os.environ.items() if k.lower() in ('http_proxy','https_proxy','no_proxy','all_proxy','node_extra_ca_certs','ssl_cert_file','requests_ca_bundle','curl_ca_bundle')}
assert not clues, clues
host=sys.argv[3] if len(sys.argv)>3 else 'en.wikipedia.org'
ips=sorted({v[4][0] for v in socket.getaddrinfo(host,443,socket.AF_INET)})
conn=http.client.HTTPSConnection(host,timeout=10)
conn.connect()
peer=conn.sock.getpeername()[0]
cert=conn.sock.getpeercert()
conn.request('GET','/wiki/Monarchy_of_the_United_Kingdom')
response=conn.getresponse()
body=response.read()
assert response.status==200 and response.version==11
managed=len(sys.argv)>2 and sys.argv[2]=='managed'
extras={}
if managed:
 assert cert['issuer']==((('commonName','Managed Network Root CA'),),)
 same=conn.sock
 conn.request('GET','/wiki/Monarchy_of_the_United_Kingdom')
 again=conn.getresponse()
 assert again.read()==body and conn.sock is same and same is not None
 extras['http11_connection_reused']=True
 assert socket.getaddrinfo('example.com',443,socket.AF_INET)
 extras['blacklisted_domain_resolves']=True
 import subprocess
 url='https://'+host+'/wiki/Monarchy_of_the_United_Kingdom'
 result=subprocess.run(['curl','--http2','-sS','-o','/tmp/probe-first','-w','%{http_version} %{num_connects}\\n',url,'-o','/tmp/probe-second',url],capture_output=True,check=True,timeout=20)
 assert result.stdout.decode().splitlines()==['2 1','2 0'],result.stdout
 assert Path('/tmp/probe-first').read_bytes()==body==Path('/tmp/probe-second').read_bytes()
 extras['http2_connection_reused']=True
 extras['http2_bodies_match']=True
conn.close()
others={}
for other in [h for h in (sys.argv[4].split(',') if len(sys.argv)>4 and sys.argv[4] else []) if h!=host]:
 extra=http.client.HTTPSConnection(other,timeout=10)
 extra.request('GET','/health' if managed else '/')
 answer=extra.getresponse();answer.read()
 others[other]={'status':answer.status,'peer':extra.sock.getpeername()[0] if extra.sock else None,'tls_verified':True}
 extra.close()
 assert answer.status==200,(other,answer.status)
extras['other_world_hosts']=others
up=http.client.HTTPSConnection('api.anthropic.com',timeout=20)
up.request('GET','/')
result=up.getresponse()
provider_status=result.status
result.read()
up.close()
try:
 socket.getaddrinfo('unlisted.invalid' if managed else 'example.com',443)
 raise AssertionError('Unknown DNS name unexpectedly allowed')
except socket.gaierror:
 pass
blocked=False
try:
 raw=socket.create_connection(('1.1.1.1',443),timeout=3)
 ssl.create_default_context().wrap_socket(raw,server_hostname='example.com')
except (OSError,ssl.SSLError):
 blocked=True
assert blocked
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert int(status['CapEff'].strip(),16)==0
assert os.getuid()==10001
private_blocked=False
try:
 socket.create_connection((sys.argv[1],80),timeout=2).close()
except OSError:
 private_blocked=True
assert private_blocked
dns_bypasses=[]
for resolver in ('127.0.0.11','1.1.1.1'):
 udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
 udp.settimeout(1)
 query=b'\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01'
 try:
  udp.sendto(query,(resolver,53))
  udp.recvfrom(4096)
  raise AssertionError('DNS bypass answered: '+resolver)
 except OSError:
  dns_bypasses.append(resolver)
 finally:
  udp.close()
print(json.dumps({'environment_clues':clues,'world_dns':ips,'peer':peer,'tls_verified':True,'issuer':cert['issuer'],'http_version':response.version,'body_sha256':hashlib.sha256(body).hexdigest(),'provider_tls_verified':True,'provider_http_status':provider_status,'unknown_dns_blocked':True,'unknown_tls_blocked':blocked,'capabilities':0,'uid':os.getuid(),'origin_direct_access_blocked':private_blocked,'dns_bypasses_blocked':dns_bypasses,**extras}))
'''


def world_hosts(folder):
    """Hosts the run's policy serves from worlds; Wikipedia first when present."""
    policy = folder / "effective-sites.json"
    if not policy.exists():
        return [WIKI[0]]
    from sandbox.site_policy import WORLD_TRANSPORTS, validate
    served = [host for host, entry in validate(json.loads(policy.read_bytes())).items() if entry.get("transport") in WORLD_TRANSPORTS]
    return sorted(served, key=lambda h: h != WIKI[0])


def preflight(compose, env, folder, world):
    container = subprocess.check_output(compose + ["ps", "-q", "wikipedia"], cwd=ROOT, env=env, text=True).strip()
    state = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    origin = next(iter(state["NetworkSettings"]["Networks"].values()))["IPAddress"]
    probe=PROBE.replace('/wiki/Monarchy_of_the_United_Kingdom','/health') if world.snapshot.get('presentation')=='on-demand-v1' else PROBE
    hosts = world_hosts(folder)
    host = hosts[0]
    # Every served host must resolve to its pinned answers and present a trusted certificate.
    result = subprocess.run(compose + ["run", "--rm", "--no-deps", "-T", "agent", "python3", "-c", probe, origin, env.get("TRUMAN_GATEWAY_ENGINE", "transparent"), host, ",".join(hosts[1:])],
                            cwd=ROOT, env=env, capture_output=True, timeout=75)
    durable(folder / "preflight.stdout", result.stdout)
    durable(folder / "preflight.stderr", result.stderr)
    if result.returncode:
        raise RuntimeError("Transparent preflight failed; see preflight.stderr")
    observed = json.loads(result.stdout)
    pinned = json.loads((folder / "network-profile.json").read_bytes())["dns"]["answers"][host]
    assert observed["world_dns"] == pinned and observed["peer"] in pinned
    answers = json.loads((folder / "network-profile.json").read_bytes())["dns"]["answers"]
    for other, seen in observed.get("other_world_hosts", {}).items():
        assert seen["peer"] in answers[other], (other, seen)
    route = world.lookup("GET", "en.wikipedia.org", "/wiki/Monarchy_of_the_United_Kingdom")
    if route:
        assert observed["body_sha256"] == route["body_blob"]
    elif world.snapshot.get('presentation') == 'captured-html-v1':
        assert observed['body_sha256'] == world.snapshot['articles']['Monarchy of the United Kingdom']['html_blob']
    elif world.snapshot.get('presentation') == 'on-demand-v1':
        assert observed['body_sha256']==sha(b'ok')
    durable(folder / "preflight.json", encoded(observed))
    for name, command in (("client-routes", ["ip", "route"]), ("client-firewall", ["iptables", "-nvL", "OUTPUT"])):
        config = subprocess.check_output(compose + ["exec", "-T", "clientnet", *command], cwd=ROOT, env=env)
        durable(folder / (name + ".txt"), config)
    records = journal(folder / "capture/events.jsonl")
    return records[-1]["seq"] if records else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=Path("data/transparent-profile-v2"))
    parser.add_argument("--managed", action="store_true")
    parser.add_argument("--site-policy", type=Path, default=ROOT / "network/sites.json")
    args = parser.parse_args()
    prepare(args.profile, args.managed, args.site_policy)


if __name__ == "__main__":
    main()
