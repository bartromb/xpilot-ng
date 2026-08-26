# XPilot NG network protocol

Phase 5 input. Written from the 4.7.3 sources rather than from any older
specification, so where this disagrees with historical documentation, this
describes what the code in this tree actually does.

The immediate purpose is the NAT audit below. The secondary purpose is that
Phase 6's bot SDK has to speak this protocol, so anything a third party would
need in order to write a client belongs here.

## Shape of the thing

Everything is UDP. There is no TCP anywhere in the game path.

A session has two phases on **two different ports**, which is the single most
important fact for anyone configuring a firewall:

```
1. contact    client  ---->  server : 15345          (the well-known port)
              client  <----  server : 15345          reply carries a NEW port
2. game       client  ---->  server : <that port>    everything from here on
              client  <----  server : <that port>
```

The server does not serve the game from 15345. On each successful login it
opens a **fresh UDP socket with its own ephemeral port**, and sends that port
number back to the client in the `ENTER_GAME_pack` reply. The client then
opens its own socket and connects to that port; 15345 takes no further part
in the session.

Source: `Setup_connection()` in `src/server/netserver.c` binds the socket and
reads back its port with `sock_get_port()`; `Contact()` in
`src/server/contact.c` replies with it; `Net_init()` in
`src/client/netclient.c` connects to it.

## Framing

| Field | Size | Notes |
|---|---|---|
| Magic | 4 bytes | `MAGIC_WORD` is `0xF4ED` in the low half; the protocol version occupies the high half |
| Packet type | 1 byte | see below |
| Payload | varies | per packet type |

Version negotiation is done by packing the version into the magic word:
`VERSION2MAGIC(V)` is `((V & 0xFFFF) << 16) | 0xF4ED`, and the server compares
against `MIN_CLIENT_VERSION`/`MAX_CLIENT_VERSION`, replying `E_VERSION` (0x0C)
on mismatch. A client announcing an unacceptable version is refused at contact
time, before any game socket is created.

There are two distinct packet-type namespaces, which is easy to trip over:

- **Contact-phase** types in `src/common/pack.h`: `ENTER_GAME_pack` (0x00),
  `CONTACT_pack` (0x31), `ENTER_QUEUE_pack`, `REPORT_STATUS_pack`,
  `MESSAGE_pack`, `LOCK_GAME_pack`, `SHUTDOWN_pack`, `KICK_PLAYER_pack`,
  `OPTION_TUNE_pack`, `OPTION_LIST_pack`.
- **Game-phase** types in `src/common/packet.h`: 92 `PKT_*` values,
  `PKT_VERIFY` (1) through the frame-update stream.

Reply codes are single bytes: `SUCCESS`, `E_NOT_FOUND` (0x07), `E_INVAL`
(0x0A), `E_VERSION` (0x0C) and others in `pack.h`.

Within the game phase there is a reliable sub-stream (`PKT_RELIABLE`) layered
over UDP, carrying anything that must not be dropped — map data, messages,
score updates — while frame state is sent unreliably and simply superseded by
the next frame.

## NAT audit

The question the roadmap asks is whether this is NAT-friendly. The answer
differs sharply depending on which end is behind the NAT.

### Client behind NAT — works

This looks alarming and is fine. The reply that matters comes from a port the
client never sent to, which would normally be dropped by an
address-restricted or port-restricted NAT. But the client does not wait to be
contacted: on receiving the new port it **opens a socket and sends to it
first** (`Net_init` → `sock_connect`, then the verify handshake). That
outbound packet creates the NAT mapping, and the server's replies arrive on
it.

So an ordinary home client needs no configuration at all, and no port
forwarding. This matches the observed behaviour — the smoke tests in this repo
connect without any special setup.

### Server behind NAT — hostile, but solvable

This is the real problem, and it has two parts.

**The contact port**, 15345, must be forwarded. That much is obvious and
unavoidable.

**Every per-connection port must also be reachable**, and by default those are
ephemeral — the kernel picks whatever is free, so the range is unpredictable
and cannot be forwarded in advance. A server behind NAT with only 15345
forwarded will complete the contact phase and then go silent, which is a
confusing failure: the client reports a successful login and then times out.

The mitigation already exists and predates this audit: the server options
`clientPortStart` and `clientPortEnd` constrain the per-connection sockets to
a fixed range (`Setup_connection()` loops over exactly that range). Set them
and forward that range plus 15345, and a NATed server works. `MAX_SELECT_FD`
and the configured `maxClients` bound how many you need.

**Recommendation for `docs/` and any packaging**: a self-hosted server should
set `clientPortStart`/`clientPortEnd` explicitly rather than relying on
ephemeral ports. The Docker and systemd work in this phase should do this by
default, because the failure mode when it is not set is silent and
hard to diagnose.

### What is *not* a problem

- **No IP addresses are embedded in the game protocol.** The server never
  tells the client its own address; the client already knows it, having
  dialled it. That avoids the classic FTP-style NAT breakage where a rewritten
  packet contains a stale private address. Only a port number crosses the
  wire, and ports survive NAT rewriting.
- **No inbound-only flows.** Every flow in the game phase is initiated by the
  client, so stateful firewalls on the client side need no rules.

## Metaserver

`src/common/metaserver.h` hardcodes:

```
META_PORT     5500
META_HOST     meta.xpilot.org
META_HOST_TWO meta2.xpilot.org
META_IP       129.242.13.151
META_IP_TWO   132.235.197.27
```

Servers announce themselves over **UDP to port 5500** as plain text
(`Meta_send()` in `src/server/metaserver.c`), gated on the `reportToMetaServer`
option. Clients query the same hosts to populate the server browser.

Both hosts are dead, which is why the client's server browser is empty and why
starting a server logs `Locating Internet Meta server... found 1... 2 not
found`. The lookup still resolves one name, so the failure is partial and
slow rather than clean.

Since the payload is plain text over UDP on a fixed port, a replacement only
has to listen on 5500 and speak the same text format. It does **not** need to
be the same implementation. `lmartinking/xpilot-metaserver` on GitHub is a
Python fork of the BloodsPilot metaserver and is the obvious starting point
rather than writing one; the roadmap already identifies it.

Note the addresses are compiled in, so pointing a client or server at a
self-hosted metaserver currently means recompiling. Making the metaserver host
an option is a small change and is worth doing as part of the replacement
work.

## Attack surface, for the security pass

The packet handlers are the interesting target, and they are 1990s C reading
attacker-controlled bytes.

Entry points, in the order an attacker reaches them:

1. `Contact()` in `src/server/contact.c` — reachable by anyone who can send a
   UDP packet to 15345, **before any authentication**, and it parses strings
   (user name, nick, display) out of the packet.
2. `Handle_setup()` and the `PKT_*` dispatch in `src/server/netserver.c` —
   reachable after login.
3. `Packet_scanf()` in `src/common/net.c` — the shared parser everything above
   funnels through; a flaw here is a flaw in every handler at once.

`Packet_scanf` is the highest-value fuzz target for exactly that reason: it is
small, it is pure parsing, it needs no network or game state to exercise, and
everything else depends on it.

### What a read of `Packet_scanf` already shows

Worth recording so the fuzzing effort starts from evidence rather than from
"1990s C is frightening".

**String reads are correctly bounded.** `%s` caps at `MAX_CHARS` (80) and `%S`
at `MSG_LEN` (256), and the callers in `contact.c` declare exactly
`char user_name[MAX_CHARS]` and friends. The index arithmetic is right too:
the loop writes `str[k++]` and then tests `k >= max_str_size`, so the last
byte written is `str[79]` — inside an 80-byte buffer. There is no pre-auth
string overflow here, which is the first thing one would look for.

**But an over-long string leaves the buffer unterminated.** When the limit is
hit, the function warns, sets a failure code and returns without writing a
`'\0'` — the caller's buffer holds 80 non-terminated bytes. That is safe only
so long as every caller checks the return value before touching the buffer.
The callers in `contact.c` do (`if (Packet_scanf(...) <= 0) return ...`), so
this is not currently a bug; it is a landmine for the next person who adds a
handler. A fuzz harness should assert on it rather than wait for someone to
step on it.

**The genuinely unexamined surface** is therefore not the string reads but the
numeric conversions and the interaction between `Sockbuf_read` refills and
partial packets — the `failure = 2` versus `failure = 3` paths above, which
differ for datagram versus locked buffers and are the sort of state machine
that fuzzing is good at and reading is bad at.
