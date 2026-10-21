# ssh configs (copy)

Copy of the shared ssh host definitions that were kept in `ThanuMahee12/shellrc`
under `ssh/shared/`. The shellrc copy is still what ssh reads on every machine
(through `~/shellrc/ssh/...` Include lines), so this copy is not live yet.

- `shared/work/` - corporate hosts, `global.config` last in the Include order.
- `shared/thanujan/` - personal identity and git hosts.

Include order and the rules for these files are documented in the shellrc
CLAUDE.md. Cutover (generating `~/.ssh/ssh_registry.config` from here and
removing the shellrc copy) is a separate, later change.
