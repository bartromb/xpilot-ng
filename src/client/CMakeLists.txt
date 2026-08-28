#
# XPilot NG, a multiplayer space war game.
#
# Code shared by the X11 and SDL clients.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.  See the COPYING file for details.
#

add_library(xpclient STATIC
    client.c
    clientcommand.c
    clientrank.c
    datagram.c
    default.c
    event.c
    gfx2d.c
    mapdata.c
    messages.c
    meta.c
    netclient.c
    option.c
    paint.c
    paintmap.c
    paintobjects.c
    query.c
    talkmacros.c
    textinterface.c
    usleep.c)

# Matches the autotools COND_SOUND conditional.
if(XPILOT_SOUND)
    target_sources(xpclient PRIVATE caudio.c sdlmixaudio.c)
    target_link_libraries(xpclient PUBLIC ${XP_SDL2_MIXER_LIBS} ${XP_SDL2_LIBS})
endif()

target_include_directories(xpclient PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(xpclient PUBLIC xpcommon xp_common_flags)
