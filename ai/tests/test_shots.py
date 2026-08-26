"""Shot positions.

Shots are the one thing in the frame stream that is not sent as coordinates.
PKT_FASTSHOT sends a type byte and then one byte pair per shot, and the type
byte is an index into a grid of 256x256 tiles over the client's view, not a
colour. Treating it as a colour -- which its name invites -- makes every shot
land in the top-left corner of the world.
"""

import math

import pytest

from xpilot_bot.frames import Frame, Self, Shot, world_shots


def _frame(view=(1024, 768), me=(5000, 4000), shots=()):
    f = Frame()
    f.self_ = Self(x=me[0], y=me[1], view_width=view[0], view_height=view[1])
    f.shots = [Shot(x=x, y=y, kind=k) for x, y, k in shots]
    return f


def test_a_shot_at_the_view_centre_is_at_our_position():
    """1024x768 gives a 4x3 tile grid. Tile 5 is column 1, row 1, so its
    origin is (256, 256) into the view; the view centre (512, 384) is then
    256 across and 128 up inside it."""
    f = _frame(shots=[(256, 128, 5)])
    (x, y, _kind), = world_shots(f)
    assert (x, y) == (5000, 4000)


def test_the_type_byte_is_a_tile_index_not_a_colour():
    """Two shots with the same byte pair but different type bytes are 256
    pixels apart, not in the same place."""
    f = _frame(shots=[(10, 10, 0), (10, 10, 1)])
    (x0, y0, _), (x1, y1, _) = world_shots(f)
    assert (x1 - x0, y1 - y0) == (256, 0)


def test_the_grid_wraps_to_the_next_row():
    f = _frame(shots=[(0, 0, 0), (0, 0, 4)])   # 4 columns, so tile 4 is row 1
    (x0, y0, _), (x1, y1, _) = world_shots(f)
    assert (x1 - x0, y1 - y0) == (0, 256)


def test_an_unknown_view_size_yields_nothing_rather_than_a_guess():
    """Placing shots confidently in the wrong place is worse than not
    reporting them: the agent cannot tell a wrong answer from a real one."""
    f = _frame(view=(0, 0), shots=[(10, 10, 0)])
    assert world_shots(f) == []


def test_no_self_state_yields_nothing():
    f = Frame()
    f.shots = [Shot(x=1, y=2, kind=0)]
    assert world_shots(f) == []


def test_positions_are_relative_to_us_so_they_move_when_we_do():
    a = world_shots(_frame(me=(5000, 4000), shots=[(10, 20, 6)]))
    b = world_shots(_frame(me=(5100, 4000), shots=[(10, 20, 6)]))
    assert b[0][0] - a[0][0] == 100
    assert b[0][1] == a[0][1]


def test_a_shot_off_our_nose_bears_the_way_we_point():
    """The property the live check confirmed: firing while stationary puts
    shots directly ahead. Here with the geometry made explicit."""
    f = _frame(view=(1024, 768), me=(5000, 4000), shots=[(256 + 100, 128, 5)])
    (x, y, _), = world_shots(f)
    bearing = math.atan2(y - 4000, x - 5000)
    assert bearing == pytest.approx(0.0), "due east, as heading 0 points"
