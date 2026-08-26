#
# XPilot NG, a multiplayer space war game.
#
# The SDL/OpenGL client.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.  See the COPYING file for details.
#

add_executable(xpilot-ng-sdl
    console.c
    DT_drawtext.c
    effects.c
    gamepad.c
    glwidgets.c
    images.c
    main.c
    radar.c
    SDL_console.c
    SDL_gfxPrimitives.c
    sdlevent.c
    sdlgui.c
    sdlinit.c
    sdlkeys.c
    sdlmeta.c
    sdlpaint.c
    sdlwindow.c
    text.c
    todo.c)

# Matches the autotools COND_SDL_GAMELOOP conditional. win32hacks.c is
# Windows-only and is not part of the CMake build.
if(XPILOT_SDL_GAMELOOP)
    target_sources(xpilot-ng-sdl PRIVATE gameloop.c)
else()
    target_sources(xpilot-ng-sdl PRIVATE gameloop_x.c)
endif()

target_link_libraries(xpilot-ng-sdl PRIVATE
    xpclient
    xpcommon
    PkgConfig::SDL2
    PkgConfig::SDL2_TTF
    OpenGL::GL
    OpenGL::GLU
    X11::X11
    X11::SM
    X11::ICE
    EXPAT::EXPAT
    ZLIB::ZLIB)

if(SDL2_IMAGE_FOUND)
    target_link_libraries(xpilot-ng-sdl PRIVATE PkgConfig::SDL2_IMAGE)
endif()

install(TARGETS xpilot-ng-sdl RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
