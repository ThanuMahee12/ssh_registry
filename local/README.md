# Per-device SSH overrides

Drop a `*.config` here to override anything in `../shared/` **on this machine
only**. Files here are git-ignored; this README is not.

Each machine's final config includes this directory **first**, and OpenSSH takes
the *first* value it sees for each keyword — so what you put here wins. Putting
an override at the bottom of a config instead does nothing at all.

```
# ssh/local/mybox.config
Host sf_bench
  HostName 10.0.0.99      # this box reaches it on a different address
```

Only override what genuinely differs. Anything true for every device belongs in
`../shared/` so it reaches your other machines through git.
