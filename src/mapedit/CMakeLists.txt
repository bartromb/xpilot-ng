#
# XPilot NG, a multiplayer space war game.
#
# The map editor.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.  See the COPYING file for details.
#

add_executable(xpilot-ng-xp-mapedit
    events.c
    expose.c
    file.c
    forms.c
    grow.c
    help.c
    main.c
    round.c
    T_Form.c
    T_Handler.c
    T_Popup.c
    T_Toolkit.c
    tools.c)

target_link_libraries(xpilot-ng-xp-mapedit PRIVATE
    xpcommon
    X11::X11
    X11::SM
    X11::ICE
    EXPAT::EXPAT
    ZLIB::ZLIB)

install(TARGETS xpilot-ng-xp-mapedit RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
