"""Observed delivery environment, captured at HTTP boundaries, outside rendering."""
import socket


def capture_local_host_aliases() -> set[str]:
    aliases = {"localhost", "127.0.0.1", "::1"}
    for host in {socket.gethostname().strip(), socket.getfqdn().strip()}:
        if host:
            aliases.add(host.lower())
    for family, remote in (
        (socket.AF_INET, ("8.8.8.8", 80)),
        (socket.AF_INET, ("1.1.1.1", 80)),
        (socket.AF_INET6, ("2001:4860:4860::8888", 80)),
    ):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.connect(remote)
                local = sock.getsockname()[0]
                if local:
                    aliases.add(str(local).strip().lower())
        except OSError:
            continue
    for host in {socket.gethostname().strip(), socket.getfqdn().strip()}:
        if not host:
            continue
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            continue
        for info in infos:
            sockaddr = info[4]
            if not sockaddr:
                continue
            local = sockaddr[0]
            if local:
                aliases.add(str(local).strip().lower())
    return aliases

