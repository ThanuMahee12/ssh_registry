"""Turn hosts into ssh config text.

OpenSSH takes the FIRST value it sees per keyword, so the `Host *` defaults are
written last: anything a real host sets wins over them.

A host with service users gets one extra block per account, e.g.
`Host ny5-predpalch01_svcP* alchmy_ny5p01_svcP*` with RemoteCommand. The
trailing `*` keeps those blocks out of VS Code's Remote Explorer, which lists
only wildcard-free names; they hijack scp/rsync, so they are interactive only.
"""

from __future__ import annotations

from .hosts import Host


def _block(patterns: list[str], lines: list[tuple[str, str]], note: str | None = None) -> str:
    out = [f"# {note}"] if note else []
    out.append("Host " + " ".join(patterns))
    out += [f"  {k} {v}" for k, v in lines]
    return "\n".join(out)


def _host_lines(h: Host) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = [("HostName", h.hostname)]
    if h.port:
        lines.append(("Port", str(h.port)))
    if h.user:
        lines.append(("User", h.user))
    if h.proxy:
        lines.append(("ProxyJump", h.proxy))
    if h.forward_agent:
        lines.append(("ForwardAgent", "yes"))
    if h.key:
        lines.append(("IdentityFile", h.key))
    if h.identities_only:
        lines.append(("IdentitiesOnly", "yes"))
    lines += list(h.options.items())
    return lines


def render(hosts: list[Host], header: str, defaults: dict[str, str]) -> str:
    blocks = [header.rstrip()]
    module = None
    for h in hosts:
        if h.module != module:
            module = h.module
            blocks.append(f"# ===== {module} " + "=" * max(3, 70 - len(module)))
        svc_any = [f"{n}_svc*" for n in h.names] if h.service_users else []
        blocks.append(_block(h.names + svc_any, _host_lines(h), h.note))
        for flag, account in h.service_users.items():
            blocks.append(_block(
                [f"{n}_svc{flag}*" for n in h.names],
                [("RequestTTY", "yes"), ("RemoteCommand", f"sudo su - {account}")],
            ))
    if defaults:
        blocks.append(_block(["*"], list(defaults.items()), "Defaults for every host; last, so any host above wins"))
    return "\n\n".join(blocks) + "\n"
