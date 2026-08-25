#
# XPilot NG, a multiplayer space war game.
#
# Shared code used by the server, clients and tools.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.  See the COPYING file for details.
#

add_library(xpcommon STATIC
    arraylist.c
    checknames.c
    config.c
    error.c
    list.c
    math.c
    net.c
    portability.c
    randommt.c
    shipshape.c
    socklib.c
    strcasecmp.c
    strdup.c
    strlcpy.c
    xpmemory.c)

target_include_directories(xpcommon PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(xpcommon PUBLIC xp_common_flags m)
