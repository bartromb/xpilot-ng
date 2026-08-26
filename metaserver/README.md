# Self-hosted metaserver

The public metaservers (`meta.xpilot.org`, `meta2.xpilot.org`) are dead, which
is why the client's server browser is empty. `xpilot_metaserver.py` is a
replacement that speaks the same protocol, so **unmodified clients and servers
can use it**.

No dependencies. Python 3.9+.

## Run it

```sh
python3 metaserver/xpilot_metaserver.py
```

That listens on:

| Port | Protocol | For |
|---|---|---|
| 5500 | UDP | game servers announcing themselves |
| 4401 | TCP | clients fetching the server list |
| 4402 | TCP | JSON, for humans and dashboards (`--http-port 0` disables) |

Both game ports are above 1024, so it does not need root.

## Point a server and a client at it

Both ends had the metaserver addresses compiled in, so this needed a new
option on each side:

```sh
# a game server that reports to your metaserver
./build/bin/xpilot-ng-server -map lib/maps/blood-music.xp2 \
    -maxRobots 2 -minRobots 2 -port 15345 -noQuit -idleRun \
    -reportToMetaServer true -metaServerHost meta.example.org

# a client whose browser reads from it
./build/bin/xpilot-ng-sdl -metaServerHost meta.example.org
```

Leave `-metaServerHost` unset and you get the historical hosts, which is to
say an empty list.

## Why not "a tiny HTTP JSON service"

That is what `ROADMAP.md` proposed, and it is not what this is. An HTTP
service cannot be read by an unmodified client: the client opens a TCP
connection to port 4401 and expects colon-separated records, and no amount of
JSON will change that without patching every client.

Since protocol compatibility is the point of this fork, the wire protocol is
the original one. The JSON endpoint is offered alongside it, for anything that
is not an XPilot client.

## The protocol, as implemented

**Servers announce over UDP 5500**, plain text, NUL-terminated:

```
add server <host>
add users <n>
add version <v>
add map <name>
...
```

and on a clean shutdown:

```
server <host>
remove
```

**Clients connect over TCP 4401** and are sent one record per line, then
disconnected. Each record is exactly **18 colon-separated fields** in this
order — the client discards any line with a different count:

```
version:host:port:users:map:sizeMap:author:status:bases:fps:
players:sound:stime:teams:timing:ip:free:queue
```

Seven of those (`port`, `users`, `bases`, `fps`, `stime`, `teams`, `queue`)
are parsed with `sscanf("%u")`, so a non-numeric value makes the client throw
the whole record away. This implementation substitutes `0` rather than risk
that.

The `ip` field is filled in from the sender's address rather than from
anything the server claims, so a server cannot list itself under someone
else's address.

Servers re-announce roughly every 180 seconds; anything unheard-from for
`--ttl` seconds (default 600) is dropped.

## Verified

End to end against real binaries, not mocks:

- a game server registers (`ADD Z6G4:15000`),
- the client's own server browser lists it (`Z6G4 | Blood's Music | 4.7.3ng`),
- the JSON endpoint reports the same data,
- and a clean server shutdown removes it from the list.

## Deploying

`packaging/xpilot-ng-metaserver.service` is a hardened systemd unit. As with
the game server, remember the firewall: **UDP 5500 and TCP 4401** both need to
be reachable, and they are different protocols on different ports.
