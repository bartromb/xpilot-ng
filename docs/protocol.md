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

### The reliable sub-stream in detail

Decoding it was needed to measure anything about a game's *outcome*, since no
score, kill or player name appears on the frame stream at all. Three
properties are easy to miss from the source and expensive to get wrong.

**Segments are not always datagrams of their own.** This is the one that
costs the most to get wrong. Before play begins, each `PKT_RELIABLE` segment
arrives as its own datagram, so a client can recognise it by its first byte.
Once frames start, `Send_end_of_frame` appends whatever reliable data is
queued to the *end of a frame update* — so the datagram begins with
`PKT_START` and the segment is somewhere in the middle of it. A client that
inspects only `data[0]` therefore works flawlessly through setup and goes
deaf the instant the game starts.

The failure is quiet and misleading. Nothing errors; the reliable stream
simply appears to stop. Player joins, scores and death notices never arrive,
so the game looks eventless. Meanwhile the server is retransmitting data it
is owed, receiving no acknowledgement, and after enough retries it drops the
connection — logged as `Goodbye … ("timeout 08")`, which reads like a network
problem rather than a parsing one. Finding a `PKT_RELIABLE` therefore means
walking the whole datagram packet by packet.

**It is a byte stream, not a packet stream.** Each `PKT_RELIABLE` segment is
`%c%hd%ld%ld` — type, payload length, offset into the stream, and a frame
number — followed by the payload. Segments arrive out of order, are
retransmitted until acknowledged, and a single packet may straddle two of
them. A decoder must therefore buffer by offset and parse only contiguous
bytes; parsing per-segment double-counts retransmissions.

**It does not start with packets.** The layout is fixed:

    [PKT_REPLY (3)] [PKT_MAGIC (5)] [setup header + map_data_len bytes] [packets…]

The setup blob is `%ld%ld%hd%hd%hd%hd%s%s%S` — `map_data_len`, mode, lives,
width, height, fps, map name, author, data URL — followed by exactly
`map_data_len` bytes of map. Only after it does the packet stream begin.
Because the length is announced, the blob can be stepped over exactly; there
is no need to guess when setup has ended.

**`PKT_PLAYER` carries two shape strings.** `Send_player` writes the base
ship shape and then an `ext` continuation, which the C client appends to the
first (`&shape[strlen(shape)]`). Reading only one leaves a string on the
stream, and since packets are undelimited, everything after it decodes as
garbage. A working reference implementation is in
[`ai/xpilot_bot/reliable.py`](../ai/xpilot_bot/reliable.py).

Types that can appear (the client's `reliable_tbl`, plus `PKT_REPLY` and
`PKT_MAGIC`, which it handles inline): `MOTD`, `MESSAGE`, `TEAM_SCORE`,
`PLAYER`, `TEAM`, `SCORE`, `TIMING`, `LEAVE`, `WAR`, `SEEK`, `BASE`, `QUIT`,
`STRING`, `SCORE_OBJECT`, `TALK_ACK`. Scores are sent as hundredths in
protocol versions ≥ 0x4F11 and as whole numbers before that.

### Shots are not sent as coordinates

`PKT_FASTSHOT` is `%c` type, `%c` count, then one byte pair per shot — and
the type byte is not a colour, despite the name it is given everywhere. It
is an index into a grid of 256×256 pixel tiles laid over the client's view
(`BASE_X`/`BASE_Y` in `src/client/paintobjects.c`), and each byte pair is an
offset inside that tile:

    x_areas = (view_width  + 255) >> 8
    y_areas = (view_height + 255) >> 8
    x_view  = (type % x_areas) * 256 + byte_x
    y_view  = ((type / x_areas) % y_areas) * 256 + byte_y

The view is centred on the player, so world position needs `PKT_SELF`'s
position *and* the view size it reports. Read the type byte as a colour and
every shot in the game piles up in one corner of the map.

`PKT_DEBRIS` uses the same tiling, which is why it occupies a whole range of
packet types rather than one.

There is no owner and no velocity in the packet, so a client cannot tell a
bullet flying at it from one it just fired, nor which way any of them are
going. The real client does not need to: it draws them and the player's eye
does the rest. Anything reasoning about them programmatically has to work
around it.

### Kills and deaths are only in the text

There is no kill packet. `PKT_SCORE` carries a life count, but on a map with
unlimited lives it never changes, so watching it detects nothing. What the
server does send is a death notice as an ordinary `PKT_MESSAGE`:

    Probe was killed by a shot from Boson.
    bot and robo crashed.
    bot smashed against a wall

These come from `sprintf` formats in `src/server/*.c`, and they are what a
human player reads too. Counting them is the only way to get kills.

One caveat that matters if the results are to be trusted: a player could
simply *type* a death notice. The server appends `" [nick]"` to everything a
player says and to nothing it says itself, so a message ending in `]` is
chat and must not be counted.

## The ship is inert until you configure it

A client must tell the server how its ship handles, with `PKT_POWER`,
`PKT_TURNSPEED` and `PKT_TURNRESISTANCE` (plus `_S` variants for the
shift-modifier), each `%c%hd` carrying the value times 256.

This reads like tuning and is not. `MIN_PLAYER_TURNSPEED` is **0.0**, and
`Player_init` starts a player at the minimum, so a client that never sends
`PKT_TURNSPEED` has a ship that **cannot turn at all**. `MIN_PLAYER_POWER`
is 5.0 against a real-client default of 55.0, so thrust is feeble for the
same reason.

Nothing reports either condition. `PKT_KEYBOARD` is accepted, the server
acknowledges it, frames keep arriving, and the heading simply never changes.
It presents as a ship that handles badly, which is an easy thing to blame on
the map, the physics, or one's own flying.

The real client's defaults, from `src/client/default.c`:

| option | default | range |
|---|---|---|
| `power` | 55.0 | 5–55 |
| `turnSpeed` | 16.0 | 0–64 |
| `turnResistance` | 0.0 | 0.0–1.0 |

## The world wraps

Most XPilot maps set `edgeWrap="yes"` — `dodgers-robots.xp2` does — and the
protocol never mentions it. Positions arrive as plain coordinates, so
subtracting them looks like it gives a relative position and does, right up
until the two objects are more than half a map apart. Then it confidently
returns the long way round.

Measured on a live 3150×3150 game, 423 samples, comparing naive subtraction
against the wrapped difference:

| | |
|---|---|
| nearest ship identified wrongly | 40.2% |
| bearing wrong by more than 0.5 rad | 55.1% |
| mean error introduced | 1.41 rad (~81°) |
| worst | 3.13 rad (~179°) |

Anything reasoning about relative position needs the map size, which is only
in the setup blob at the head of the reliable stream — the frame stream never
says how big the world is.

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
