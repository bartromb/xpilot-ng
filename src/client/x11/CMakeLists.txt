#
# XPilot NG, a multiplayer space war game.
#
# The plain X11 client.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.  See the COPYING file for details.
#

add_executable(xpilot-ng-x11
    about.c
    bitmaps.c
    colors.c
    configure.c
    dbuff.c
    guimap.c
    guiobjects.c
    join.c
    paintdata.c
    painthud.c
    paintradar.c
    record.c
    talk.c
    welcome.c
    widget.c
    xdefault.c
    xevent.c
    xeventhandlers.c
    xinit.c
    xpaint.c
    xpilot.c)

target_link_libraries(xpilot-ng-x11 PRIVATE
    xpclient
    xpcommon
    X11::X11
    X11::SM
    X11::ICE
    EXPAT::EXPAT
    ZLIB::ZLIB)

install(TARGETS xpilot-ng-x11 RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
