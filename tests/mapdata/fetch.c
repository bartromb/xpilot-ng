/*
 * XPilot NG, a multiplayer space war game.
 *
 * Calls the client's own Mapdata_setup() on a URL, exactly as the client does
 * when it joins a server whose map names a data package -- without needing a
 * window, a GL context or a server. tests/mapdata/run.sh drives it.
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation; either version 2 of the License, or (at your option)
 * any later version.  See the COPYING file for details.
 */

#include <stdio.h>

/* Normally defined by gfx2d.c, which this test does not link. */
char *realTexturePath = NULL;

int Mapdata_setup(const char *urlstr);
void init_error(const char *prog);

int main(int argc, char **argv)
{
    int ok;

    if (argc != 2) {
	fprintf(stderr, "usage: %s URL\n", argv[0]);
	return 2;
    }
    init_error(argv[0]);
    ok = Mapdata_setup(argv[1]);
    printf("Mapdata_setup -> %s\n", ok ? "true" : "false");
    return ok ? 0 : 1;
}
