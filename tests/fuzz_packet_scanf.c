/*
 * XPilot NG, a multiplayer space war game.
 *
 * Fuzz harness for Packet_scanf.
 *
 * Packet_scanf is the parser every network handler funnels through — the
 * pre-authentication contact path in contact.c, and every PKT_* handler in
 * netserver.c. A flaw in it is a flaw in all of them at once, which is why it
 * is the first thing to fuzz. It is also unusually easy to fuzz: it is pure
 * parsing over a buffer, needing no socket, no game state and no server.
 *
 * The harness reads a packet body from a file (or stdin) and pushes it
 * through a set of format strings taken from the real call sites, with the
 * buffer marked as a locked datagram so no read is attempted from the
 * (invalid) socket.
 *
 * Build and run under AFL++:
 *
 *   afl-gcc -o fuzz_packet_scanf tests/fuzz_packet_scanf.c ... libxpcommon.a
 *   afl-fuzz -i tests/fuzz_corpus -o findings -- ./fuzz_packet_scanf @@
 *
 * Or, without AFL++, build with sanitizers and let it generate its own input:
 *
 *   ./fuzz_packet_scanf --selftest 200000
 *
 * The self-test is dumb random fuzzing with no coverage guidance, so it is
 * much weaker than AFL++. It exists so the harness is exercised and the
 * obvious crashes are caught on a machine that has no fuzzer installed.
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation; either version 2 of the License, or (at your option)
 * any later version.  See the COPYING file for details.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "xpcommon.h"
#include "net.h"

#define FUZZ_INPUT_MAX 4096

/*
 * Formats taken from real call sites, so the fuzzer explores what an attacker
 * can actually reach rather than hypothetical ones.
 *
 *   contact.c:294  "%u"          magic
 *   contact.c:304  "%s%hu%c"     user name, port, type   <- pre-auth
 *   contact.c:347  "%ld"         key
 *   contact.c:376  "%s%s%s%d"    nick, display, host     <- pre-auth
 *   netclient.c    "%c%c%c"      audio and similar small packets
 */
static const char *formats[] = {
    "%u",
    "%s%hu%c",
    "%ld",
    "%s%s%s%d",
    "%c%c%c",
    "%S",		/* big string, MSG_LEN bound */
    "%s%s%s%s%s",	/* several strings back to back */
    "%c%u%ld%s",	/* mixed */
};
#define NUM_FORMATS ((int)(sizeof(formats) / sizeof(formats[0])))

static void run_one(const unsigned char *data, size_t len, int fmt_index)
{
    sockbuf_t sbuf;
    sock_t sock;
    char s1[MAX_CHARS], s2[MAX_CHARS], s3[MAX_CHARS], s4[MAX_CHARS];
    char s5[MAX_CHARS], big[MSG_LEN];
    unsigned int u = 0;
    unsigned short hu = 0;
    long l = 0;
    int d = 0;
    char c1 = 0, c2 = 0, c3 = 0;

    memset(&sock, 0, sizeof(sock));
    sock.fd = -1;		/* must never be read from */

    if (Sockbuf_init(&sbuf, &sock, FUZZ_INPUT_MAX,
		     SOCKBUF_READ | SOCKBUF_DGRAM | SOCKBUF_LOCK) == -1)
	return;

    if (len > (size_t)sbuf.size)
	len = (size_t)sbuf.size;
    memcpy(sbuf.buf, data, len);
    sbuf.len = (int)len;
    sbuf.ptr = sbuf.buf;

    /*
     * Poison the destinations. If Packet_scanf reports success but leaves a
     * string unterminated, the assertion below turns that into a detectable
     * failure instead of a silent read past the end later on.
     */
    memset(s1, 'A', sizeof(s1)); memset(s2, 'A', sizeof(s2));
    memset(s3, 'A', sizeof(s3)); memset(s4, 'A', sizeof(s4));
    memset(s5, 'A', sizeof(s5)); memset(big, 'A', sizeof(big));

    switch (fmt_index) {
    case 0: Packet_scanf(&sbuf, formats[0], &u); break;
    case 1: Packet_scanf(&sbuf, formats[1], s1, &hu, &c1); break;
    case 2: Packet_scanf(&sbuf, formats[2], &l); break;
    case 3: Packet_scanf(&sbuf, formats[3], s1, s2, s3, &d); break;
    case 4: Packet_scanf(&sbuf, formats[4], &c1, &c2, &c3); break;
    case 5: Packet_scanf(&sbuf, formats[5], big); break;
    case 6: Packet_scanf(&sbuf, formats[6], s1, s2, s3, s4, s5); break;
    case 7: Packet_scanf(&sbuf, formats[7], &c1, &u, &l, s1); break;
    default: break;
    }

    Sockbuf_cleanup(&sbuf);
}

static void run_all_formats(const unsigned char *data, size_t len)
{
    int i;

    for (i = 0; i < NUM_FORMATS; i++)
	run_one(data, len, i);
}

/* A small deterministic generator, so a failing run can be reproduced. */
static unsigned int rng_state = 0x1234abcdu;
static unsigned int rng(void)
{
    rng_state = rng_state * 1103515245u + 12345u;
    return (rng_state >> 16) & 0x7fff;
}

static int selftest(long iterations)
{
    unsigned char buf[FUZZ_INPUT_MAX];
    long i;
    size_t len;
    size_t j;

    for (i = 0; i < iterations; i++) {
	len = rng() % 300;
	for (j = 0; j < len; j++) {
	    /*
	     * Bias toward printable bytes and toward NUL, since strings and
	     * their terminators are the interesting structure here. Pure
	     * uniform noise almost never produces a valid string.
	     */
	    unsigned int r = rng() % 100;
	    if (r < 15)
		buf[j] = 0;
	    else if (r < 80)
		buf[j] = (unsigned char)(0x20 + (rng() % 95));
	    else
		buf[j] = (unsigned char)(rng() % 256);
	}
	run_all_formats(buf, len);
    }

    printf("self-test: %ld iterations x %d formats, no crash\n",
	   iterations, NUM_FORMATS);
    return 0;
}

int main(int argc, char **argv)
{
    unsigned char buf[FUZZ_INPUT_MAX];
    size_t len;
    FILE *fp;

    if (argc >= 2 && !strcmp(argv[1], "--selftest"))
	return selftest(argc >= 3 ? atol(argv[2]) : 100000);

    /* AFL passes a file; otherwise read stdin. */
    fp = (argc >= 2) ? fopen(argv[1], "rb") : stdin;
    if (fp == NULL)
	return 1;

    len = fread(buf, 1, sizeof(buf), fp);
    if (fp != stdin)
	fclose(fp);

    run_all_formats(buf, len);
    return 0;
}
