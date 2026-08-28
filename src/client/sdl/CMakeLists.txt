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

# Matches the autotools COND_SDL_GAMELOOP conditional. gameloop_x.c drives
# the loop through Xlib directly; gameloop.c is pure SDL and is the only one
# that compiles off X11.
if(XPILOT_SDL_GAMELOOP)
    target_sources(xpilot-ng-sdl PRIVATE gameloop.c)
else()
    target_sources(xpilot-ng-sdl PRIVATE gameloop_x.c)
endif()

if(WIN32)
    target_sources(xpilot-ng-sdl PRIVATE win32hacks.c)
endif()

target_link_libraries(xpilot-ng-sdl PRIVATE
    xpclient
    xpcommon
    ${XP_SDL2_LIBS}
    ${XP_SDL2_TTF_LIBS}
    OpenGL::GL
    EXPAT::EXPAT
    ZLIB::ZLIB)

# GLU is not part of the Windows SDK the way it is on Unix; the OpenGL
# package only reports it where it exists.
if(OPENGL_GLU_FOUND)
    target_link_libraries(xpilot-ng-sdl PRIVATE OpenGL::GLU)
endif()

# Only linked when the X11 game loop is in use -- see above.
if(NOT XPILOT_SDL_GAMELOOP)
    target_link_libraries(xpilot-ng-sdl PRIVATE X11::X11 X11::SM X11::ICE)
endif()

if(HAVE_SDL_IMAGE)
    target_link_libraries(xpilot-ng-sdl PRIVATE ${XP_SDL2_IMAGE_LIBS})
endif()

install(TARGETS xpilot-ng-sdl RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
