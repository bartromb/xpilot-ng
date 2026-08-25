#
# XPilot NG, a multiplayer space war game.
#
# The XPilot NG game server.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.  See the COPYING file for details.
#

add_executable(xpilot-ng-server
    alliance.c
    asteroid.c
    cannon.c
    cell.c
    cmdline.c
    collision.c
    command.c
    contact.c
    event.c
    fileparser.c
    frame.c
    gravity.c
    id.c
    item.c
    laser.c
    map.c
    metaserver.c
    modifiers.c
    netserver.c
    object.c
    objpos.c
    option.c
    parser.c
    player.c
    polygon.c
    race.c
    rank.c
    recwrap.c
    robot.c
    robotdef.c
    rules.c
    saudio.c
    sched.c
    score.c
    server.c
    ship.c
    shot.c
    showtime.c
    srecord.c
    suibotdef.c
    tag.c
    target.c
    teamcup.c
    treasure.c
    tuner.c
    update.c
    walls.c
    wormhole.c
    xp2map.c
    xpmap.c)

target_link_libraries(xpilot-ng-server PRIVATE
    xpcommon
    EXPAT::EXPAT
    ZLIB::ZLIB)

install(TARGETS xpilot-ng-server RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
