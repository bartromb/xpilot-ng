#
# XPilot NG, a multiplayer space war game.
#
# The recording playback tool.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.  See the COPYING file for details.
#

add_executable(xpilot-ng-replay
    buttons.c
    xp-replay.c)

# xp-replay.h includes recordfmt.h from src/client. The replay tool needs those
# headers but does not link libxpclient, matching the legacy INCLUDES line in
# the autotools build.
target_include_directories(xpilot-ng-replay PRIVATE
    "${CMAKE_SOURCE_DIR}/src/client")

target_link_libraries(xpilot-ng-replay PRIVATE
    xpcommon
    X11::X11
    X11::SM
    X11::ICE
    EXPAT::EXPAT
    ZLIB::ZLIB)

install(TARGETS xpilot-ng-replay RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
