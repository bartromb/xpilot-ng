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
# Options. Names and defaults mirror the autotools --enable/--disable flags.
# ---------------------------------------------------------------------------

option(XPILOT_X11_CLIENT   "Build the X11 client"                ON)
option(XPILOT_SDL_CLIENT   "Build the SDL/OpenGL client"         ON)
option(XPILOT_REPLAY       "Build the replay tool"               ON)
option(XPILOT_MAPEDIT      "Build the map editor"                ON)
option(XPILOT_SOUND        "Enable OpenAL sound"                 OFF)
option(XPILOT_SDL_GAMELOOP "Use the SDL game loop (not the X11-optimised one)" OFF)
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

# X11 is needed by both clients, the replay tool and the map editor.
if(XPILOT_X11_CLIENT OR XPILOT_SDL_CLIENT OR XPILOT_REPLAY OR XPILOT_MAPEDIT)
    find_package(X11 REQUIRED)
    if(NOT X11_SM_LIB OR NOT X11_ICE_LIB)
        message(FATAL_ERROR
            "libSM and libICE are required (install libsm-dev and libice-dev)")
    endif()
endif()

if(XPILOT_SDL_CLIENT)
    find_package(OpenGL REQUIRED)
    if(NOT OPENGL_GLU_FOUND)
        message(FATAL_ERROR "GLU is required (install libglu1-mesa-dev)")
    endif()

    # SDL 1.2, which on current distributions is provided by sdl12-compat.
    # Phase 2 replaces this with SDL2 outright.
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(SDL12 REQUIRED IMPORTED_TARGET sdl)
    pkg_check_modules(SDL_TTF REQUIRED IMPORTED_TARGET SDL_ttf)
    pkg_check_modules(SDL_IMAGE IMPORTED_TARGET SDL_image)
    if(SDL_IMAGE_FOUND)
        set(HAVE_SDL_IMAGE TRUE)
    endif()
endif()

if(XPILOT_SOUND)
    find_package(OpenAL REQUIRED)
    find_library(ALUT_LIBRARY NAMES alut)
    find_path(ALUT_INCLUDE_DIR NAMES AL/alut.h)
    if(NOT ALUT_LIBRARY OR NOT ALUT_INCLUDE_DIR)
        # Autotools downgrades this to a warning and silently builds without
        # sound, which is easy to miss. Fail loudly instead.
        message(FATAL_ERROR
            "XPILOT_SOUND=ON but freealut was not found (install libalut-dev). "
            "Configure with -DXPILOT_SOUND=OFF to build without sound.")
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

# src/common/version.h is checked into git and is byte-identical to what
# autotools regenerates, so it is used as-is rather than regenerated here.
# Revisit when autotools is removed at the end of Phase 1.

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

install(FILES
    lib/defaults.txt
    lib/password.txt
    lib/robots.txt
    lib/shipshapes.txt
    DESTINATION "${XP_PKGDATADIR}")

install(DIRECTORY lib/maps/     DESTINATION "${XP_PKGDATADIR}/maps"
        FILES_MATCHING PATTERN "*.xp2" PATTERN "*.xpd")
install(DIRECTORY lib/fonts/    DESTINATION "${XP_PKGDATADIR}/fonts"
        FILES_MATCHING PATTERN "*.fnt" PATTERN "*.bdf" PATTERN "*.ttf")
install(DIRECTORY lib/textures/ DESTINATION "${XP_PKGDATADIR}/textures"
        FILES_MATCHING PATTERN "*.ppm" PATTERN "*.png")
if(XPILOT_SOUND)
    install(DIRECTORY lib/sound/ DESTINATION "${XP_PKGDATADIR}/sound")
endif()

# ---------------------------------------------------------------------------

message(STATUS "")
message(STATUS "XPilot NG ${PROJECT_VERSION} configuration")
message(STATUS "  build type .......... ${CMAKE_BUILD_TYPE}")
message(STATUS "  server .............. yes")
message(STATUS "  X11 client .......... ${XPILOT_X11_CLIENT}")
message(STATUS "  SDL client .......... ${XPILOT_SDL_CLIENT}")
message(STATUS "  replay tool ......... ${XPILOT_REPLAY}")
message(STATUS "  map editor .......... ${XPILOT_MAPEDIT}")
message(STATUS "  sound (OpenAL) ...... ${XPILOT_SOUND}")
message(STATUS "  data directory ...... ${XP_DATADIR}")
message(STATUS "")
