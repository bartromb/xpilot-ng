"""Tests for reliable sub-stream decoding.

The reassembler is the part worth testing hardest: it is fed by a network,
so out-of-order arrival, retransmission and mid-packet segment boundaries are
normal traffic rather than edge cases, and a mistake in any of them
desynchronises the stream permanently rather than dropping one packet.
"""

import struct

import pytest

from xpilot_bot import protocol as p
from xpilot_bot.reliable import ReliableStream


def player(pid, nick, myself=0, team=0, mychar=b" "):
    return (struct.pack(">Bh", p.PKT_PLAYER, pid) + bytes([team]) + mychar
            + nick.encode() + b"\0" + b"user\0" + b"host\0"
            # Two shape strings, as Send_player writes them.
            + b"shape\0" + b"ext\0"
            + bytes([myself]))


def score(pid, pts, life):
    return struct.pack(">BhihBB", p.PKT_SCORE, pid, int(pts * 100), life,
                       ord(" "), ord(" "))


def message(text):
    return bytes([p.PKT_MESSAGE]) + text.encode() + b"\0"


def feed_all(stream, blob, chunk=None, start=0):
    """Feed a blob, optionally split into fixed-size chunks."""
    if chunk is None:
        stream.feed(start, blob)
        return
    for i in range(0, len(blob), chunk):
        stream.feed(start + i, blob[i : i + chunk])


# ---------------------------------------------------------------- parsing


def test_player_and_score():
    s = ReliableStream()
    feed_all(s, player(7, "bot", myself=1) + score(7, 12.5, 3))
    assert not s.desynced
    assert s.board.own_id == 7
    assert s.board.me.nick == "bot"
    assert s.board.me.score == pytest.approx(12.5)
    assert s.board.me.life == 3


def test_death_is_a_falling_life_count():
    s = ReliableStream()
    feed_all(s, player(1, "bot", myself=1))
    feed_all(s, score(1, 0, 3), start=s.offset)
    assert s.board.me.deaths == 0, "the first score is not a transition"
    feed_all(s, score(1, 0, 2), start=s.offset)
    feed_all(s, score(1, 0, 1), start=s.offset)
    assert s.board.me.deaths == 2
    # A rise is a new round, not a resurrection.
    feed_all(s, score(1, 0, 3), start=s.offset)
    assert s.board.me.deaths == 2
    assert s.board.me.rounds == 1


def test_leave_removes_the_player():
    s = ReliableStream()
    feed_all(s, player(1, "a") + player(2, "b")
             + struct.pack(">Bh", p.PKT_LEAVE, 1))
    assert set(s.board.players) == {2}


def test_messages_and_score_events():
    s = ReliableStream()
    blob = (message("bot was killed by robot")
            + struct.pack(">BiHH", p.PKT_SCORE_OBJECT, 1000, 5, 6)
            + b"+10\0")
    feed_all(s, blob)
    assert not s.desynced
    assert s.board.messages[0].text == "bot was killed by robot"
    ev = s.board.score_events[0]
    assert (ev.score, ev.x, ev.y, ev.text) == (10.0, 5, 6, "+10")


# ----------------------------------------------------------- reassembly


@pytest.mark.parametrize("chunk", [1, 2, 3, 5, 7, 13, 64])
def test_any_segmentation_gives_the_same_result(chunk):
    """A packet split across segments must survive the split.

    Chunk 1 is the pathological case: every packet straddles boundaries and
    every string arrives a byte at a time.
    """
    blob = player(3, "bot", myself=1) + score(3, 7.25, 5) + message("hello")
    s = ReliableStream()
    feed_all(s, blob, chunk=chunk)
    assert not s.desynced, f"desynced at chunk size {chunk}"
    assert s.board.me.score == pytest.approx(7.25)
    assert s.board.messages[0].text == "hello"
    assert s.offset == len(blob)


def test_out_of_order_segments_are_held_then_applied():
    blob = player(3, "bot", myself=1) + score(3, 7.25, 5)
    cut = 10
    s = ReliableStream()
    s.feed(cut, blob[cut:])              # second half first
    assert s.board.players == {}, "must not parse across a gap"
    s.feed(0, blob[:cut])                # gap closes
    assert not s.desynced
    assert s.board.me.score == pytest.approx(7.25)


def test_retransmissions_are_idempotent():
    """The server retransmits unacknowledged segments; duplicates must not
    be parsed twice, or one death would be counted as several."""
    s = ReliableStream()
    feed_all(s, player(1, "bot", myself=1))
    sc3, sc2 = score(1, 0, 3), score(1, 0, 2)
    off = s.offset
    s.feed(off, sc3)
    s.feed(off, sc3)                     # exact duplicate
    s.feed(off, sc3)
    s.feed(off + len(sc3), sc2)
    s.feed(off, sc3 + sc2)               # overlapping retransmission
    assert s.board.me.deaths == 1
    assert s.board.me.life == 2


def test_partial_trailing_packet_waits_rather_than_desyncing():
    blob = player(3, "bot") + score(3, 1.0, 2)
    s = ReliableStream()
    s.feed(0, blob[:-1])                 # one byte short
    assert not s.desynced
    assert s.board.players[3].life == 0, "incomplete packet must not apply"
    s.feed(len(blob) - 1, blob[-1:])
    assert s.board.players[3].life == 2


def test_unknown_type_is_reported_not_guessed():
    """An unknown type cannot be skipped -- its length is unknown, so the
    honest response is to stop and say so rather than resynchronise onto
    whatever byte comes next."""
    s = ReliableStream()
    feed_all(s, player(1, "a") + bytes([250]) + b"junk")
    assert s.desynced
    assert s.desynced_at == 250
    assert s.board.unknown.get(250) == 1
    assert s.board.players[1].nick == "a", "packets before it still applied"


def test_summary_counts_both_sides():
    s = ReliableStream()
    feed_all(s, player(1, "bot", myself=1) + player(2, "robot"))
    off = s.offset
    feed_all(s, score(1, 30.0, 3) + score(2, 10.0, 3), start=off)
    off = s.offset
    feed_all(s, score(2, 10.0, 1), start=off)
    d = s.board.summary()
    assert d["own_score"] == pytest.approx(30.0)
    assert d["own_deaths"] == 0
    assert d["opponents"] == 1
    assert d["opponent_deaths_total"] == 2
