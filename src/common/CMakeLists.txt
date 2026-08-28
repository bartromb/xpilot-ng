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

# libm is a separate library on Unix and part of the C runtime on Windows,
# where asking for it fails the link outright.
if(WIN32)
    target_link_libraries(xpcommon PUBLIC xp_common_flags)
    # Sockets live in ws2_32 rather than libc: recv, select, htons,
    # WSAGetLastError and __WSAFDIsSet (which is what FD_ISSET expands to)
    # are all in there. PUBLIC because socklib.c is here but its callers are
    # in the server and the client.
    target_link_libraries(xpcommon PUBLIC ws2_32)
else()
    target_link_libraries(xpcommon PUBLIC xp_common_flags m)
endif()
