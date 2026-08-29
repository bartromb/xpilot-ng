/* 
 * Adapted from 'The UNIX Programming Environment' by Kernighan & Pike
 * and an example from the manualpage for vprintf by
 * Gaute Nessan, University of Tromsoe (gaute@staff.cs.uit.no).
 *
 * Modified by Bjoern Stabell <bjoern@xpilot.org>.
 * Windows mods and memory leak detection by Dick Balaska <dick@xpilot.org>.
 */
#include "xpcommon.h"

/*
 * This file defines several entry points:
 *
 * init_error()		- Initialize the error routine, accepts program name
 *			  as input.
 * error()		- perror() with printf functionality.
 * warn(), ...
 */

/*
 * File local static data.
 */
#define	MAX_PROG_LENGTH	32
static char progname[MAX_PROG_LENGTH];

static const char *prog_basename(const char *prog)
{
#ifndef _WINDOWS
    char *p;

    p = strrchr(prog, '/');

    return (p != NULL) ? (p + 1) : prog;
#else
    return "XPilot NG";
#endif
}


/*
 * Functions.
 */
void init_error(const char *prog)
{
    const char *p = prog_basename(prog);   /* Beautify argv[0] */

    strlcpy(progname, p, MAX_PROG_LENGTH);
}

#ifndef _WINDOWS

/*
 * Ok, let's do it the ANSI C way.
 */
void xpinfo(const char *fmt, ...)
{
    size_t len;
    va_list ap;

    va_start(ap, fmt);

    if (progname[0] != '\0')
	fprintf(stderr, "%s: INFO: ", progname);

    vfprintf(stderr, fmt, ap);

    len = strlen(fmt);
    if (len == 0 || fmt[len - 1] != '\n')
	fprintf(stderr, "\n");

    va_end(ap);
}

void warn(const char *fmt, ...)
{
    size_t len;
    va_list ap;

    va_start(ap, fmt);

    if (progname[0] != '\0')
	fprintf(stderr, "%s: WARNING: ", progname);

    vfprintf(stderr, fmt, ap);

    len = strlen(fmt);
    if (len == 0 || fmt[len - 1] != '\n')
	fprintf(stderr, "\n");

    va_end(ap);
}

void error(const char *fmt, ...)
{
    size_t len;
    va_list ap;
    int e = errno;

    va_start(ap, fmt);

    if (progname[0] != '\0')
	fprintf(stderr, "%s: ERROR: ", progname);

    vfprintf(stderr, fmt, ap);

    if (e != 0)
	fprintf(stderr, ": (%s)", strerror(e));

    len = strlen(fmt);
    if (len == 0 || fmt[len - 1] != '\n')
	fprintf(stderr, "\n");

    va_end(ap);
}

void fatal(const char *fmt, ...)
{
    size_t len;
    va_list ap;

    va_start(ap, fmt);

    if (progname[0] != '\0')
	fprintf(stderr, "%s: FATAL: ", progname);

    vfprintf(stderr, fmt, ap);

    len = strlen(fmt);
    if (len == 0 || fmt[len - 1] != '\n')
	fprintf(stderr, "\n");

    va_end(ap);

    exit(1);
}

void dumpcore(const char *fmt, ...)
{
    size_t len;
    va_list ap;

    va_start(ap, fmt);

    if (progname[0] != '\0')
	fprintf(stderr, "%s: ABORT: ", progname);

    vfprintf(stderr, fmt, ap);

    len = strlen(fmt);
    if (len == 0 || fmt[len - 1] != '\n')
	fprintf(stderr, "\n");

    va_end(ap);

    abort();
}
#endif /* _WINDOWS */

#ifdef _WINDOWS
/*
 * Every diagnostic on Windows funnelled through here, and here it died: the
 * only surviving output was Trace(), which expands to nothing unless _DEBUG
 * is defined (the MessageBox that used to sit here had been commented out).
 * In a release build error(), warn(), fatal() and xpinfo() therefore printed
 * nothing at all -- a Windows client could refuse to start, or quit for a
 * reason it had carefully worded, and leave an empty log behind. Write to
 * stderr like every other platform does.
 */
static void Win_show_error(const char *level, char *s)
{
    static int inerror = FALSE;
    size_t len;

    Trace("Error: %s\n", s);

    if (inerror) return;
    inerror = TRUE;

    if (progname[0] != '\0')
	fprintf(stderr, "%s: %s: ", progname, level);
    else
	fprintf(stderr, "%s: ", level);

    fputs(s, stderr);

    len = strlen(s);
    if (len == 0 || s[len - 1] != '\n')
	fputc('\n', stderr);

    /* Windows leaves stderr block-buffered when it is redirected to a file,
     * so a message about an imminent exit would otherwise be lost. */
    fflush(stderr);

    inerror = FALSE;
}

void xpinfo(const char *fmt, ...)
{
    va_list ap;
    char s[512];

    va_start(ap, fmt);
    vsnprintf(s, sizeof s, fmt, ap);
    va_end(ap);

    Win_show_error("INFO", s);
}

void error(const char *fmt, ...)
{
    va_list ap;
    char s[512];
    int e = errno;
    size_t len;

    va_start(ap, fmt);
    vsnprintf(s, sizeof s, fmt, ap);
    va_end(ap);

    /* Match the POSIX build, which reports what errno had to say. */
    if (e != 0) {
	len = strlen(s);
	if (len < sizeof s - 1)
	    snprintf(s + len, sizeof s - len, ": (%s)", strerror(e));
    }

    Win_show_error("ERROR", s);
}

void warn(const char *fmt, ...)
{
    va_list ap;
    char s[512];

    va_start(ap, fmt);
    vsnprintf(s, sizeof s, fmt, ap);
    va_end(ap);

    Win_show_error("WARNING", s);
}

void fatal(const char *fmt, ...)
{
    va_list ap;
    char s[512];

    va_start(ap, fmt);
    vsnprintf(s, sizeof s, fmt, ap);
    va_end(ap);

    Win_show_error("FATAL", s);

    exit(1);
}

void dumpcore(const char *fmt, ...)
{
    va_list ap;
    char s[512];

    va_start(ap, fmt);
    vsnprintf(s, sizeof s, fmt, ap);
    va_end(ap);

    Win_show_error("ABORT", s);

    exit(1);
}

#endif
