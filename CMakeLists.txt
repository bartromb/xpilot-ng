#
# XPilot NG, a multiplayer space war game.
#
# CMake build. Runs alongside the legacy autotools build until it reaches
# parity; see docs/build-audit.md for what autotools does and ROADMAP.md
# Phase 1 for the migration plan.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

cmake_minimum_required(VERSION 3.16)

project(xpilot-ng
    VERSION 4.7.3
    DESCRIPTION "XPilot NG, a multiplayer space war game"
    LANGUAGES C)

set(XP_PACKAGE_NAME "XPilot NG")
set(XP_BUGREPORT "xpilot-hacks@lists.sourceforge.net")

include(CheckIncludeFile)
include(CheckSymbolExists)
include(CheckStructHasMember)
include(GNUInstallDirs)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    # Matches the autotools default of -g -O2.
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "Build type" FORCE)
endif()

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

# All executables land in build/bin so the smoke-test invocations in
# BUILDING.md work with a single, predictable path.
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

# ---------------------------------------------------------------------------
# Platform
#
# The X11 client, the replay tool and the map editor are built on Xlib and
# only make sense where there is an X server. The SDL client and the server
# are portable, so those are what Windows and macOS get. Defaults are chosen
# per platform rather than left to fail at find_package time with an error
# about libSM that tells a Windows user nothing.
# ---------------------------------------------------------------------------

if(WIN32 OR APPLE)
    set(XP_HAVE_X11 OFF)
else()
    set(XP_HAVE_X11 ON)
endif()

# ---------------------------------------------------------------------------
# Options. Names and defaults mirror the autotools --enable/--disable flags.
# ---------------------------------------------------------------------------

option(XPILOT_X11_CLIENT   "Build the X11 client"                ${XP_HAVE_X11})
option(XPILOT_SDL_CLIENT   "Build the SDL/OpenGL client"         ON)
option(XPILOT_REPLAY       "Build the replay tool"               ${XP_HAVE_X11})
option(XPILOT_MAPEDIT      "Build the map editor"                ${XP_HAVE_X11})

# Sound follows the library. Defaulting this OFF meant a plain configure
# produced a mute build, and the Linux package was shipped from exactly such a
# build for months while Windows and macOS passed -DXPILOT_SOUND=ON -- so the
# game was silent on Linux only, for no stated reason. Probe first and default
# to what the machine can actually do. Asking for -DXPILOT_SOUND=ON without the
# library is still a hard error rather than a mute binary.
find_package(PkgConfig QUIET)
if(PKG_CONFIG_FOUND)
    pkg_check_modules(SDL2_MIXER IMPORTED_TARGET SDL2_mixer)
endif()
if(SDL2_MIXER_FOUND)
    set(XP_SDL2_MIXER_LIBS PkgConfig::SDL2_MIXER)
else()
    find_package(SDL2_mixer QUIET)
    if(SDL2_mixer_FOUND)
        set(SDL2_MIXER_FOUND TRUE)
        set(XP_SDL2_MIXER_LIBS SDL2_mixer::SDL2_mixer)
    endif()
endif()
# The audio backend is built on SDL2, so it cannot come on by itself when the
# SDL client is off.
if(SDL2_MIXER_FOUND AND XPILOT_SDL_CLIENT)
    set(XP_SOUND_DEFAULT ON)
else()
    set(XP_SOUND_DEFAULT OFF)
endif()
option(XPILOT_SOUND        "Enable sound (SDL2_mixer)"           ${XP_SOUND_DEFAULT})
# The X11-optimised game loop calls Xlib directly, so off-X11 platforms need
# the portable one. It is not a preference there, it is the only one that
# compiles.
if(XP_HAVE_X11)
    set(XP_SDL_GAMELOOP_DEFAULT OFF)
else()
    set(XP_SDL_GAMELOOP_DEFAULT ON)
endif()
option(XPILOT_SDL_GAMELOOP "Use the SDL game loop (not the X11-optimised one)" ${XP_SDL_GAMELOOP_DEFAULT})
option(XPILOT_DBE          "X Double Buffer Extension support"   OFF)
option(XPILOT_MBX          "X Multibuffer Extension support"     OFF)
option(XPILOT_PLOCKSERVER  "Lock the server into memory"         OFF)
option(XPILOT_SELECT_SCHED "Alternative select()-based server scheduling" OFF)
option(XPILOT_DEVELOPMENT  "Enable development-only code"        OFF)

set(DBE          ${XPILOT_DBE})
set(MBX          ${XPILOT_MBX})
set(PLOCKSERVER  ${XPILOT_PLOCKSERVER})
set(SELECT_SCHED ${XPILOT_SELECT_SCHED})
set(DEVELOPMENT  ${XPILOT_DEVELOPMENT})

# libxpclient is only needed if at least one client is being built.
if(XPILOT_X11_CLIENT OR XPILOT_SDL_CLIENT)
    set(XPILOT_NEED_CLIENT_LIB TRUE)
else()
    set(XPILOT_NEED_CLIENT_LIB FALSE)
endif()

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

find_package(ZLIB REQUIRED)
find_package(EXPAT REQUIRED)

# X11 is needed by the X11 client, the replay tool and the map editor. The
# SDL client needs it too, but only when it is using the X11-optimised game
# loop -- with XPILOT_SDL_GAMELOOP it is pure SDL.
if(XPILOT_X11_CLIENT OR XPILOT_REPLAY OR XPILOT_MAPEDIT
   OR (XPILOT_SDL_CLIENT AND NOT XPILOT_SDL_GAMELOOP))
    find_package(X11 REQUIRED)
    if(NOT X11_SM_LIB OR NOT X11_ICE_LIB)
        message(FATAL_ERROR
            "libSM and libICE are required (install libsm-dev and libice-dev)")
    endif()
endif()

if(XPILOT_SDL_CLIENT)
    find_package(OpenGL REQUIRED)
    if(NOT OPENGL_GLU_FOUND AND NOT WIN32)
        message(FATAL_ERROR "GLU is required (install libglu1-mesa-dev)")
    endif()

    # pkg-config is how SDL2 is found on Linux and on MSYS2. Elsewhere --
    # notably a Homebrew or vcpkg install -- SDL2 ships CMake config files,
    # so fall back to those rather than requiring pkg-config everywhere.
    find_package(PkgConfig QUIET)
    if(PKG_CONFIG_FOUND)
        pkg_check_modules(SDL2 IMPORTED_TARGET sdl2)
        pkg_check_modules(SDL2_TTF IMPORTED_TARGET SDL2_ttf)
        pkg_check_modules(SDL2_IMAGE IMPORTED_TARGET SDL2_image)
    endif()

    if(SDL2_FOUND)
        set(XP_SDL2_LIBS PkgConfig::SDL2)
    else()
        find_package(SDL2 REQUIRED)
        set(XP_SDL2_LIBS SDL2::SDL2)
    endif()

    if(SDL2_TTF_FOUND)
        set(XP_SDL2_TTF_LIBS PkgConfig::SDL2_TTF)
    else()
        find_package(SDL2_ttf REQUIRED)
        set(XP_SDL2_TTF_LIBS SDL2_ttf::SDL2_ttf)
    endif()

    if(SDL2_IMAGE_FOUND)
        set(HAVE_SDL_IMAGE TRUE)
        set(XP_SDL2_IMAGE_LIBS PkgConfig::SDL2_IMAGE)
    else()
        find_package(SDL2_image QUIET)
        if(SDL2_image_FOUND)
            set(HAVE_SDL_IMAGE TRUE)
            set(XP_SDL2_IMAGE_LIBS SDL2_image::SDL2_image)
        endif()
    endif()
endif()

if(XPILOT_SOUND)
    # Audio is SDL2_mixer as of Phase 3; the OpenAL/freealut backend is gone.
    # The library was probed next to the option above.
    if(NOT SDL2_MIXER_FOUND)
        # Autotools downgraded a missing audio library to a warning and
        # silently produced a mute binary, which was easy to miss. Fail loudly.
        message(FATAL_ERROR
            "XPILOT_SOUND=ON but SDL2_mixer was not found "
            "(install libsdl2-mixer-dev). "
            "Configure with -DXPILOT_SOUND=OFF to build without sound.")
    endif()
    if(NOT XPILOT_SDL_CLIENT)
        message(FATAL_ERROR
            "XPILOT_SOUND=ON requires the SDL client (XPILOT_SDL_CLIENT=ON); "
            "the audio backend is built on SDL2.")
    endif()
    set(SOUND TRUE)
endif()

# ---------------------------------------------------------------------------
# Configuration probes
#
# Only the macros that source files under src/ actually read; see
# docs/build-audit.md. The legacy AC_FUNC_* probes are deliberately dropped,
# as nothing in the tree reads what they produce.
# ---------------------------------------------------------------------------

set(XP_HEADER_CHECKS
    arpa/inet.h             HAVE_ARPA_INET_H
    arpa/nameser.h          HAVE_ARPA_NAMESER_H
    assert.h                HAVE_ASSERT_H
    bstring.h               HAVE_BSTRING_H
    ctype.h                 HAVE_CTYPE_H
    errno.h                 HAVE_ERRNO_H
    fcntl.h                 HAVE_FCNTL_H
    float.h                 HAVE_FLOAT_H
    inttypes.h              HAVE_INTTYPES_H
    limits.h                HAVE_LIMITS_H
    math.h                  HAVE_MATH_H
    memory.h                HAVE_MEMORY_H
    netdb.h                 HAVE_NETDB_H
    net/if.h                HAVE_NET_IF_H
    netinet/in.h            HAVE_NETINET_IN_H
    netinet/tcp.h           HAVE_NETINET_TCP_H
    pwd.h                   HAVE_PWD_H
    resolv.h                HAVE_RESOLV_H
    setjmp.h                HAVE_SETJMP_H
    signal.h                HAVE_SIGNAL_H
    stdarg.h                HAVE_STDARG_H
    stdint.h                HAVE_STDINT_H
    stdlib.h                HAVE_STDLIB_H
    string.h                HAVE_STRING_H
    strings.h               HAVE_STRINGS_H
    sys/fcntl.h             HAVE_SYS_FCNTL_H
    sys/file.h              HAVE_SYS_FILE_H
    sys/filio.h             HAVE_SYS_FILIO_H
    sys/inttypes.h          HAVE_SYS_INTTYPES_H
    sys/ioctl.h             HAVE_SYS_IOCTL_H
    sys/lock.h              HAVE_SYS_LOCK_H
    sys/mman.h              HAVE_SYS_MMAN_H
    sys/param.h             HAVE_SYS_PARAM_H
    sys/select.h            HAVE_SYS_SELECT_H
    sys/socket.h            HAVE_SYS_SOCKET_H
    sys/sockio.h            HAVE_SYS_SOCKIO_H
    sys/stat.h              HAVE_SYS_STAT_H
    sys/time.h              HAVE_SYS_TIME_H
    sys/types.h             HAVE_SYS_TYPES_H
    unistd.h                HAVE_UNISTD_H
    values.h                HAVE_VALUES_H)

# X11 headers are only probed when something that needs them is being built,
# so a server-only build does not require X11 development packages.
if(X11_FOUND)
    list(APPEND XP_HEADER_CHECKS
        X11/X.h                          HAVE_X11_X_H
        X11/Xlib.h                       HAVE_X11_XLIB_H
        X11/Xos.h                        HAVE_X11_XOS_H
        X11/Xutil.h                      HAVE_X11_XUTIL_H
        X11/keysym.h                     HAVE_X11_KEYSYM_H
        X11/Xatom.h                      HAVE_X11_XATOM_H
        X11/Xmd.h                        HAVE_X11_XMD_H
        X11/extensions/Xdbe.h            HAVE_X11_EXTENSIONS_XDBE_H
        X11/extensions/multibuf.h        HAVE_X11_EXTENSIONS_MULTIBUF_H)
endif()

list(LENGTH XP_HEADER_CHECKS _xp_len)
math(EXPR _xp_last "${_xp_len} - 1")
foreach(_i RANGE 0 ${_xp_last} 2)
    list(GET XP_HEADER_CHECKS ${_i} _hdr)
    math(EXPR _j "${_i} + 1")
    list(GET XP_HEADER_CHECKS ${_j} _var)
    check_include_file("${_hdr}" ${_var})
endforeach()

check_symbol_exists(gettimeofday  "sys/time.h" HAVE_GETTIMEOFDAY)
check_symbol_exists(strcasecmp    "strings.h"  HAVE_STRCASECMP)
check_symbol_exists(strncasecmp   "strings.h"  HAVE_STRNCASECMP)
check_symbol_exists(strlcat       "string.h"   HAVE_STRLCAT)
check_symbol_exists(strlcpy       "string.h"   HAVE_STRLCPY)

check_struct_has_member("struct sockaddr" sa_len "sys/types.h;sys/socket.h"
    HAVE_SA_LEN)

# Both are unconditionally true on every platform this build supports; the
# source still tests them, so define them rather than probing.
set(STDC_HEADERS TRUE)
set(TIME_WITH_SYS_TIME TRUE)

set(HAVE_LIBEXPAT TRUE)
set(HAVE_LIBZ TRUE)

configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/config.h.in"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/config.h"
    @ONLY)

# src/common/version.h is a checked-in, hand-maintained header rather than a
# generated one. It is deliberately not regenerated: it carries the authors'
# names in ISO-8859-1, and regenerating it through CMake would risk re-encoding
# them. Guard against the version drifting from project(VERSION) instead.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/src/common/version.h" _xp_version_h)
if(NOT _xp_version_h MATCHES "define[ \t]+VERSION[ \t]+\"([0-9][^\"]*)\"")
    message(FATAL_ERROR "Could not parse VERSION out of src/common/version.h")
endif()
if(NOT CMAKE_MATCH_1 STREQUAL PROJECT_VERSION)
    message(FATAL_ERROR
        "Version mismatch: src/common/version.h says ${CMAKE_MATCH_1}, "
        "CMakeLists.txt project(VERSION) says ${PROJECT_VERSION}. "
        "Update both.")
endif()
unset(_xp_version_h)

set(XP_DATADIR "${CMAKE_INSTALL_FULL_DATADIR}/${PROJECT_NAME}/")

# Applied to every target, matching the autotools AM_CPPFLAGS.
add_library(xp_common_flags INTERFACE)
target_include_directories(xp_common_flags INTERFACE
    "${CMAKE_CURRENT_BINARY_DIR}/generated")
target_compile_definitions(xp_common_flags INTERFACE
    HAVE_CONFIG_H
    "CONF_DATADIR=\"${XP_DATADIR}\"")

# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

add_subdirectory(src/common)

if(XPILOT_NEED_CLIENT_LIB)
    add_subdirectory(src/client)
endif()

add_subdirectory(src/server)

if(XPILOT_X11_CLIENT)
    add_subdirectory(src/client/x11)
endif()
if(XPILOT_SDL_CLIENT)
    add_subdirectory(src/client/sdl)
endif()
if(XPILOT_REPLAY)
    add_subdirectory(src/replay)
endif()
if(XPILOT_MAPEDIT)
    add_subdirectory(src/mapedit)
endif()

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------

set(XP_PKGDATADIR "${CMAKE_INSTALL_DATADIR}/${PROJECT_NAME}")

# Data files. These lists are taken verbatim from the lib/*/Makefile.am
# xpilot*_DATA variables rather than globbed, because autotools ships a
# deliberate subset: 12 of the maps on disk, not all of them.
install(FILES
    lib/defaults.txt
    lib/password.txt
    lib/robots.txt
    lib/shipshapes.txt
    DESTINATION "${XP_PKGDATADIR}")

set(XP_MAPS
    lib/maps/blood-music.xp2
    lib/maps/circle2.xp2
    lib/maps/dodgers-robots.xp2
    lib/maps/dodgers-legacy.xp2
    lib/maps/dragon-1.0.xp2
    lib/maps/ndh.xp2
    lib/maps/ndh.xpd
    lib/maps/polybloods.xp2
    lib/maps/sadistic_bastard_v2.xp2
    lib/maps/spaceball.xp2
    lib/maps/teamcup.xp
    lib/maps/tourmination.xp2)
install(FILES ${XP_MAPS} DESTINATION "${XP_PKGDATADIR}/maps")

set(XP_FONTS
    lib/fonts/ConsoleFont.bmp
    lib/fonts/VeraMoBd.ttf
    lib/fonts/FreeSansBoldOblique.ttf)
install(FILES ${XP_FONTS} DESTINATION "${XP_PKGDATADIR}/fonts")

set(XP_TEXTURES
    lib/textures/acwise_grav.ppm
    lib/textures/allitems.ppm
    lib/textures/asteroid.ppm
    lib/textures/asteroidconcentrator.ppm
    lib/textures/ball.ppm
    lib/textures/ball_gray.ppm
    lib/textures/ball_gray16.ppm
    lib/textures/base_down.ppm
    lib/textures/base_left.ppm
    lib/textures/base_right.ppm
    lib/textures/base_up.ppm
    lib/textures/bullet.ppm
    lib/textures/bullet2.ppm
    lib/textures/bullet_blue.ppm
    lib/textures/bullet_green.ppm
    lib/textures/cannon_down.ppm
    lib/textures/cannon_left.ppm
    lib/textures/cannon_right.ppm
    lib/textures/cannon_up.ppm
    lib/textures/checkpoint.ppm
    lib/textures/clouds.ppm
    lib/textures/concentrator.ppm
    lib/textures/cwise_grav.ppm
    lib/textures/fuel2.ppm
    lib/textures/fuelcell.ppm
    lib/textures/holder1.ppm
    lib/textures/holder2.ppm
    lib/textures/huditems.ppm
    lib/textures/logo.ppm
    lib/textures/metabtndown.png
    lib/textures/metabtnup.png
    lib/textures/metalite.ppm
    lib/textures/meter.ppm
    lib/textures/mine_other.ppm
    lib/textures/mine_team.ppm
    lib/textures/minus.ppm
    lib/textures/missile.ppm
    lib/textures/moon.ppm
    lib/textures/paused.ppm
    lib/textures/plus.ppm
    lib/textures/radar.ppm
    lib/textures/radar2.ppm
    lib/textures/radar3.ppm
    lib/textures/refuel.ppm
    lib/textures/rock4.ppm
    lib/textures/sdlmetabg.png
    lib/textures/shield.ppm
    lib/textures/ship.ppm
    lib/textures/ship_enemy.ppm
    lib/textures/ship_friend.ppm
    lib/textures/ship_blue.ppm
    lib/textures/ship_red.ppm
    lib/textures/ship_red2.ppm
    lib/textures/ship_red3.ppm
    lib/textures/sparks.ppm
    lib/textures/target.ppm
    lib/textures/volcanic.ppm
    lib/textures/wall_bottom.ppm
    lib/textures/wall_dl.ppm
    lib/textures/wall_dr.ppm
    lib/textures/wall_fi.ppm
    lib/textures/wall_left.ppm
    lib/textures/wall_right.ppm
    lib/textures/wall_top.ppm
    lib/textures/wall_ul.ppm
    lib/textures/wall_ull.ppm
    lib/textures/wall_ur.ppm
    lib/textures/wall_url.ppm
    lib/textures/wormhole.ppm)
install(FILES ${XP_TEXTURES} DESTINATION "${XP_PKGDATADIR}/textures")

if(XPILOT_SOUND)
    install(DIRECTORY lib/sound/ DESTINATION "${XP_PKGDATADIR}/sound")
endif()

# mapconvert.py ships in pkgdatadir (autotools dist_pkgdata_DATA).
install(FILES mapconvert.py DESTINATION "${XP_PKGDATADIR}")

# Man pages. Sources are *.man and install as *.6, matching the autotools
# dist_man6_MANS rule. All five install unconditionally, as they do there,
# regardless of which targets are enabled.
foreach(_man xpilot-ng-sdl xpilot-ng-x11 xpilot-ng-server xpilot-ng-replay
             xpilot-ng-xp-mapedit)
    install(FILES "doc/man/${_man}.man"
            DESTINATION "${CMAKE_INSTALL_MANDIR}/man6"
            RENAME "${_man}.6")
endforeach()

# ---------------------------------------------------------------------------
# Packaging
#
# Build a .deb with:   cpack -G DEB --config build/CPackConfig.cmake
# or from the build dir:  cpack -G DEB
# ---------------------------------------------------------------------------

set(CPACK_PACKAGE_NAME "${PROJECT_NAME}")
set(CPACK_PACKAGE_VERSION "${PROJECT_VERSION}")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "${PROJECT_DESCRIPTION}")
set(CPACK_PACKAGE_VENDOR "XPilot NG contributors")
set(CPACK_PACKAGE_HOMEPAGE_URL "https://github.com/bartromb/xpilot-ng")
set(CPACK_RESOURCE_FILE_LICENSE "${CMAKE_CURRENT_SOURCE_DIR}/COPYING")
set(CPACK_PACKAGE_INSTALL_DIRECTORY "${PROJECT_NAME}")
set(CPACK_PACKAGING_INSTALL_PREFIX "/usr")
set(CPACK_STRIP_FILES TRUE)

# Debian
set(CPACK_DEBIAN_PACKAGE_MAINTAINER "bartromb <bart.rombaut@gmail.com>")
set(CPACK_DEBIAN_PACKAGE_SECTION "games")
set(CPACK_DEBIAN_PACKAGE_PRIORITY "optional")
set(CPACK_DEBIAN_FILE_NAME DEB-DEFAULT)

# Let dpkg-shlibdeps work the dependencies out from what actually got linked,
# rather than maintaining a hand-written list that drifts. It needs the
# binaries, so it only runs at package time.
set(CPACK_DEBIAN_PACKAGE_SHLIBDEPS ON)

include(CPack)

# ---------------------------------------------------------------------------

message(STATUS "")
message(STATUS "XPilot NG ${PROJECT_VERSION} configuration")
message(STATUS "  build type .......... ${CMAKE_BUILD_TYPE}")
message(STATUS "  server .............. yes")
message(STATUS "  X11 client .......... ${XPILOT_X11_CLIENT}")
message(STATUS "  SDL client .......... ${XPILOT_SDL_CLIENT}")
message(STATUS "  replay tool ......... ${XPILOT_REPLAY}")
message(STATUS "  map editor .......... ${XPILOT_MAPEDIT}")
message(STATUS "  sound (SDL2_mixer) .. ${XPILOT_SOUND}")
message(STATUS "  data directory ...... ${XP_DATADIR}")
message(STATUS "")
