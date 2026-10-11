"""Turn host rows into ssh config text.

OpenSSH takes the FIRST value it sees per keyword, so pattern rows (the
`Host *` defaults) are written last: anything a real host sets wins over them.

A host with service accounts gets one extra block per account, e.g.
`Host alchmy_ny5p01_svcP*` with RemoteCommand. The trailing `*` keeps those
blocks out of VS Code's Remote Explorer, which lists only wildcard-free names;
they hijack scp/rsync, so they are interactive-only by design.
"""

from __future__ import annotations

from .hosts import Host


def _block(patterns: list[str], lines: list[tuple[str, str]], note: str | None) -> str:
    out = []
    if note:
        out.append(f"# {note}")
    out.append("Host " + " ".join(patterns))
    out += [f"  {k} {v}" for k, v in lines]
    return "\n".join(out)


def _host_lines(h: Host) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    if h.hostname:
        lines.append(("HostName", h.hostname))
    if h.port:
        lines.append(("Port", str(h.port)))
    if h.user:
        lines.append(("User", h.user))
    if h.proxy:
        lines.append(("ProxyJump", h.proxy))
    if h.forward_agent:
        lines.append(("ForwardAgent", "yes"))
    lines += [("IdentityFile", f"~/.ssh/{k}") for k in h.keys]
    if h.identities_only:
        lines.append(("IdentitiesOnly", "yes"))
    lines += list(h.options.items())
    return lines


def render(hosts: list[Host], header: str) -> str:
    blocks = [header.rstrip()]
    for h in [h for h in hosts if not h.is_pattern] + [h for h in hosts if h.is_pattern]:
        patterns = [h.host, *h.aliases] + ([f"{h.host}_svc*"] if h.svc else [])
        blocks.append(_block(patterns, _host_lines(h), h.note))
        for k, account in h.svc.items():
            blocks.append(_block(
                [f"{h.host}_svc{k}*"],
                [("RequestTTY", "yes"), ("RemoteCommand", f"sudo su - {account}")],
                None,
            ))
    return "\n\n".join(blocks) + "\n"
