/*
 * XPilot NG, a multiplayer space war game.
 *
 * Copyright (C) 2001 Juha Lindström <juhal@users.sourceforge.net>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 */

#include "xpclient.h"

#include <dirent.h>

#ifdef HAVE_LIBCURL
# include <curl/curl.h>
#endif

/* kps - you should be able to change this without a recompile */
#define DATADIR ".xpilot_data"
#define COPY_BUF_SIZE 8192

/*
 * Limits on a map data package. A real one holds a map and a dozen or so
 * textures in well under a megabyte. The package comes from a URL that
 * whichever server the player joined chose, so these bound what a hostile
 * server can make the client store, not what a real package needs.
 */
#define MAPDATA_MAX_BYTES	(64L * 1024 * 1024)	/* downloaded, and unpacked */
#define MAPDATA_MAX_FILES	1024
#define MAPDATA_MAX_NAME	128

typedef struct {
    char *protocol;
    char *host;
    int   port;
    const char *path;
    char *query;
} URL;

static int Mapdata_extract(const char *name);
static int Mapdata_download(const char *urlstr, const URL *url,
			    const char *filePath);
static int Url_parse(const char *urlstr, URL *url);
static void Url_free_parsed(URL *url);

static bool setup_done = false;

int Mapdata_setup(const char *urlstr)
{
    URL url;
    const char *name, *dir = NULL;
    char path[1024], buf[1024], dirlist[1024], dirbuf[1024], *ptr;
    int rv = false;

    if (setup_done)
	return true;

    memset(path, 0, sizeof(path));
    memset(buf, 0, sizeof(buf));

    if (!Url_parse(urlstr, &url)) {
	warn("malformed URL: %s", urlstr);
	return false;
    }

    for (name = url.path + strlen(url.path) - 1; name > url.path; name--) {
	if (*(name - 1) == '/')
	    break;
    }

    if (*name == '\0') {
	warn("no file name in URL: %s", urlstr);
	goto end;
    }

    if (realTexturePath != NULL) {
	char *tok;

	/*
	 * strtok() writes NULs into whatever it walks. realTexturePath is the
	 * list every later texture lookup searches, so tokenising it in place
	 * would cut it down to its first entry and quietly break texture
	 * loading for the rest of the session. Walk a copy instead.
	 */
	strlcpy(dirlist, realTexturePath, sizeof dirlist);
	for (tok = strtok(dirlist, ":"); tok; tok = strtok(NULL, ":")) {
	    if (access(tok, R_OK | W_OK | X_OK) == 0) {
		strlcpy(dirbuf, tok, sizeof dirbuf);
		dir = dirbuf;
		break;
	    }
	}
    }
	
    if (dir == NULL) {

	/* realTexturePath hasn't got a directory with proper access rights */
	/* so lets create one into users home dir */

	char *home = getenv("HOME");
	int n;

#ifdef _WINDOWS
	/*
	 * Windows does not set HOME. A client installed where it cannot
	 * write -- Program Files, which is where the installer puts it -- so
	 * had nowhere at all to keep downloaded map data, and every map that
	 * names a package loaded without its textures. Windows provides a
	 * per-user local application data directory for exactly this.
	 */
	if (home == NULL || home[0] == '\0')
	    home = getenv("LOCALAPPDATA");
#endif

	if (home == NULL) {
	    errno = 0;
	    error("nowhere to keep map data: no texture directory is "
		  "writable, and HOME is not set");
	    goto end;
	}

	if (strlen(home) == 0)
	    n = snprintf(buf, sizeof buf, "%s", DATADIR);
	else if (home[strlen(home) - 1] == PATHNAME_SEP)
	    n = snprintf(buf, sizeof buf, "%s%s", home, DATADIR);
	else
	    n = snprintf(buf, sizeof buf, "%s%c%s", home, PATHNAME_SEP, DATADIR);
	if (n < 0 || n >= (int)sizeof buf) {
	    error("HOME is too long to keep map data under: %s", home);
	    goto end;
	}

	if (access(buf, F_OK) != 0) {
	    if (mkdir(buf, S_IRWXU | S_IRWXG | S_IRWXO) == -1) {
		/* dir is still NULL at this point; the directory is buf. */
		error("failed to create directory %s", buf);
		goto end;
	    }
	}

	dir = buf;
    }

    {
	int n;

	if (strlen(dir) == 0)
	    n = snprintf(path, sizeof path, "%s", name);
	else if (dir[strlen(dir) - 1] == PATHNAME_SEP)
	    n = snprintf(path, sizeof path, "%s%s", dir, name);
	else
	    n = snprintf(path, sizeof path, "%s%c%s", dir, PATHNAME_SEP, name);
	if (n < 0 || n >= (int)sizeof path) {
	    error("map data path for %s is too long", name);
	    goto end;
	}
    }

    if (strrchr(path, '.') == NULL) {
	error("no extension in file name %s.", name);
	goto end;
    }

    /* temporarily make path point to the directory name */
    ptr = strrchr(path, '.');
    *ptr = '\0';

    /* add this new texture directory to texturePath */
    if (realTexturePath == NULL) {
	realTexturePath = strdup(path);
    } else {
	char *temp = XMALLOC(char, strlen(realTexturePath) + strlen(path) + 2);
	if (temp == NULL) {
	    error("not enough memory to new realTexturePath");
	    goto end;
	}
	sprintf(temp, "%s:%s", realTexturePath, path);
	free(realTexturePath);
	realTexturePath = temp;
    }

    if (access(path, F_OK) == 0) {
	warn("Required bitmaps have already been downloaded.");
	rv = true;
	goto end;
    }
    /* reset path so that it points to the package file name */
    *ptr = '.';

    warn("Downloading map data from %s to %s.", urlstr, path);

    if (!Mapdata_download(urlstr, &url, path)) {
	warn("downloading map data failed");
	goto end;
    }

    if (!Mapdata_extract(path)) {
	warn("extracting map data failed");
	/* Refused or damaged: the package is untrusted and of no further use,
	 * and the next connect downloads it afresh anyway. */
	remove(path);
	goto end;
    }

    rv = true;
    setup_done = true;

 end:
    Url_free_parsed(&url);
    return rv;
}


/*
 * Whether a name inside a map data package is safe to create. The package
 * comes from a URL the server chose, so the names are untrusted. Allow only
 * what real packages use -- "bakedmud.pnm", "moss1.jpg.pnm", "ndh-1.3.xp2" --
 * which rules out a path separator on any platform, a drive letter, and "."
 * and "..". The old check refused only the separator of the platform it was
 * built for, so on Windows "../" went straight through.
 */
static bool Mapdata_name_ok(const char *s)
{
    size_t i, n = strlen(s);

    if (n == 0 || n > MAPDATA_MAX_NAME)
	return false;
    if (strcmp(s, ".") == 0 || strcmp(s, "..") == 0)
	return false;
    for (i = 0; i < n; i++) {
	char c = s[i];

	if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
	      || (c >= '0' && c <= '9')
	      || c == '.' || c == '-' || c == '_' || c == '+'))
	    return false;
    }
    return true;
}

/*
 * Remove a partly extracted package. Mapdata_setup() treats an existing
 * directory as a finished download, so leaving one behind after a failure
 * would mean that map never gets its textures -- and after a refused package,
 * would keep whatever the hostile one managed to write.
 */
static void Mapdata_discard(const char *dir)
{
    DIR *d;
    struct dirent *e;
    char path[1024];

    if ((d = opendir(dir)) != NULL) {
	while ((e = readdir(d)) != NULL) {
	    if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0)
		continue;
	    if (snprintf(path, sizeof path, "%s%c%s", dir, PATHNAME_SEP,
			 e->d_name) < (int)sizeof path)
		remove(path);
	}
	closedir(d);
    }
    rmdir(dir);
}

static int Mapdata_extract(const char *name)
{
    gzFile in;
    FILE *out = NULL;
    int retval, count, i;
    size_t rlen, wlen, len;
    char dir[1024], fname[1024], buf[COPY_BUF_SIZE], *ptr, *sep, *end;
    long size, total = 0;

    if (snprintf(dir, sizeof dir, "%s", name) >= (int)sizeof dir) {
	error("map data path is too long: %s", name);
	return 0;
    }
    ptr = strrchr(dir, '.');
    if (ptr == NULL) {
	error("file name has no extension %s", dir);
	return 0;
    }
    *ptr = '\0';

    if (mkdir(dir, S_IRWXU | S_IRWXG | S_IRWXO) == -1) {
	error("failed to create directory %s", dir);
	return 0;
    }

    if ((in = gzopen(name, "rb")) == NULL) {
	error("failed to open %s for reading", name);
	rmdir(dir);
	return 0;
    }

    if (gzgets(in, buf, COPY_BUF_SIZE) == Z_NULL
	|| sscanf(buf, "XPD %d", &count) != 1
	|| count < 0 || count > MAPDATA_MAX_FILES) {
	error("invalid header in %s", name);
	goto fail;
    }

    for (i = 0; i < count; i++) {

	if (gzgets(in, buf, COPY_BUF_SIZE) == Z_NULL) {
	    error("failed to read file info from %s", name);
	    goto fail;
	}

	/*
	 * Each entry starts with a line "<name> <size>". It used to be read
	 * with sscanf("%s"), which has no width: a name longer than the
	 * 256-byte buffer it was scanned into overwrote the stack. Split the
	 * line by hand instead, and refuse one too long to have fitted.
	 */
	len = strlen(buf);
	if (len == 0 || buf[len - 1] != '\n') {
	    error("file info in %s is too long or cut off", name);
	    goto fail;
	}
	while (len > 0 && (buf[len - 1] == '\n' || buf[len - 1] == '\r'))
	    buf[--len] = '\0';

	sep = strrchr(buf, ' ');
	if (sep == NULL) {
	    error("failed to parse file info in %s", name);
	    goto fail;
	}
	*sep = '\0';
	errno = 0;
	size = strtol(sep + 1, &end, 10);
	if (end == sep + 1 || *end != '\0' || errno != 0 || size < 0) {
	    error("invalid file size in %s", name);
	    goto fail;
	}
	for (ptr = sep; ptr > buf && (ptr[-1] == ' ' || ptr[-1] == '\t'); )
	    *--ptr = '\0';

	if (!Mapdata_name_ok(buf)) {
	    errno = 0;
	    error("refusing map data in %s: unsafe file name \"%.64s\"",
		  name, buf);
	    goto fail;
	}

	if (size > MAPDATA_MAX_BYTES - total) {
	    errno = 0;
	    error("refusing map data in %s: it unpacks to more than %ld bytes",
		  name, MAPDATA_MAX_BYTES);
	    goto fail;
	}
	total += size;

	if (snprintf(fname, sizeof fname, "%s%c%s", dir, PATHNAME_SEP, buf)
	    >= (int)sizeof fname) {
	    error("map data path is too long in %s", name);
	    goto fail;
	}

	warn("Extracting %s (%ld)", fname, size);

	if ((out = fopen(fname, "wb")) == NULL) {
	    error("failed to open %s for writing", fname);
	    goto fail;
	}

	while (size > 0) {
	    retval = gzread(in, buf, MIN(COPY_BUF_SIZE, (unsigned)size));
	    if (retval == -1) {
		error("error when reading %s", name);
		goto fail;
	    }
	    if (retval == 0) {
		error("unexpected end of file %s", name);
		goto fail;
	    }

	    rlen = retval;
	    wlen = fwrite(buf, 1, rlen, out);
	    if (wlen != rlen) {
		error("failed to write to %s", fname);
		goto fail;
	    }

	    size -= rlen;
	}

	if (fclose(out) != 0) {
	    out = NULL;
	    error("failed to write to %s", fname);
	    goto fail;
	}
	out = NULL;
    }

    gzclose(in);
    return 1;

 fail:
    if (out != NULL)
	fclose(out);
    gzclose(in);
    Mapdata_discard(dir);
    return 0;
}


#ifdef HAVE_LIBCURL

static size_t Mapdata_write(char *data, size_t size, size_t nmemb, void *f)
{
    return fwrite(data, size, nmemb, (FILE *)f);
}

static int Mapdata_download(const char *urlstr, const URL *url,
			    const char *filePath)
{
    static bool curl_ready = false;
    char errbuf[CURL_ERROR_SIZE];
    CURL *curl;
    CURLcode res;
    FILE *f;
    int rv = false;

    UNUSED_PARAM(url);

    if (!curl_ready) {
	if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
	    error("could not initialise libcurl");
	    return false;
	}
	curl_ready = true;
    }

    if ((curl = curl_easy_init()) == NULL) {
	error("could not create a download handle");
	return false;
    }

    if ((f = fopen(filePath, "wb")) == NULL) {
	error("failed to open %s", filePath);
	curl_easy_cleanup(curl);
	return false;
    }

    errbuf[0] = '\0';
    curl_easy_setopt(curl, CURLOPT_URL, urlstr);
    curl_easy_setopt(curl, CURLOPT_ERRORBUFFER, errbuf);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, Mapdata_write);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, f);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, PACKAGE "/" VERSION);

    /*
     * The host every map in circulation points at now answers http:// with
     * a redirect to https://. Following it, over TLS, is the reason this
     * function uses libcurl at all.
     */
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_MAXREDIRS, 5L);

    /*
     * The URL is whatever the server sent. Fetch it over the web and nothing
     * else -- after a redirect as well as before -- so a server cannot point
     * the client at file:// or any other protocol libcurl happens to speak.
     */
#if LIBCURL_VERSION_NUM >= 0x075500
    curl_easy_setopt(curl, CURLOPT_PROTOCOLS_STR, "http,https");
    curl_easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS_STR, "http,https");
#else
    curl_easy_setopt(curl, CURLOPT_PROTOCOLS,
		     (long)(CURLPROTO_HTTP | CURLPROTO_HTTPS));
    curl_easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS,
		     (long)(CURLPROTO_HTTP | CURLPROTO_HTTPS));
#endif
    curl_easy_setopt(curl, CURLOPT_MAXFILESIZE_LARGE,
		     (curl_off_t)MAPDATA_MAX_BYTES);

    /* An error page is a failure, not something to unpack as map data. */
    curl_easy_setopt(curl, CURLOPT_FAILONERROR, 1L);

    /* This runs during login: give up on a dead host or a stalled transfer
     * rather than leaving the player staring at a frozen window. */
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 15L);
    curl_easy_setopt(curl, CURLOPT_LOW_SPEED_LIMIT, 1L);
    curl_easy_setopt(curl, CURLOPT_LOW_SPEED_TIME, 30L);

#if defined(_WINDOWS) && defined(CURLSSLOPT_NATIVE_CA)
    /* A Windows build can be unpacked anywhere, so the CA bundle path fixed
     * at build time cannot be relied on. Trust what Windows trusts. */
    curl_easy_setopt(curl, CURLOPT_SSL_OPTIONS, (long)CURLSSLOPT_NATIVE_CA);
#endif

    res = curl_easy_perform(curl);
    if (res == CURLE_OK)
	rv = true;
    else {
	/* error() appends strerror(errno), and errno here is whatever the last
	 * system call left behind -- libcurl's own message is the whole story. */
	errno = 0;
	error("map data download failed: %s",
	      errbuf[0] != '\0' ? errbuf : curl_easy_strerror(res));
    }

    if (fclose(f) != 0) {
	error("Error closing texture file %s", filePath);
	rv = false;
    }

    /* A partial package must not be left where it could be unpacked later. */
    if (!rv)
	remove(filePath);

    curl_easy_cleanup(curl);
    return rv;
}

#else /* !HAVE_LIBCURL */

static int Mapdata_download(const char *urlstr, const URL *url,
			    const char *filePath)
{
    char buf[1024];
    int rv, header, c, len, i;
    sock_t s;
    FILE *f = NULL;
    size_t n;

    UNUSED_PARAM(urlstr);

    /*
     * This downloader speaks plain HTTP only. It used to accept anything
     * starting "http", https included, and then send the request unencrypted
     * to port 80 -- say plainly instead that this build cannot do it.
     */
    if (strcmp("http", url->protocol) != 0) {
	errno = 0;
	error("cannot fetch %s map data: this client was built without libcurl, "
	      "which HTTPS needs", url->protocol);
	return false;
    }

    if (sock_open_tcp(&s) == SOCK_IS_ERROR) {
	error("failed to create a socket");
	return false;
    }
    if (sock_connect(&s, url->host, url->port) == SOCK_IS_ERROR) {
	error("couldn't connect to download address");
	sock_close(&s);
	return false;
    }

    if (url->query) {
	if (snprintf(buf, sizeof buf,
	     "GET %s?%s HTTP/1.1\r\nHost: %s:%d\r\nConnection: close\r\n\r\n",
	     url->path, url->query, url->host, url->port) == -1) {
	    error("too long URL");
	    sock_close(&s);
	    return false;
	}

    } else {
	if (snprintf(buf, sizeof buf,
	     "GET %s HTTP/1.1\r\nHost: %s:%d\r\nConnection: close\r\n\r\n",
	     url->path, url->host, url->port) == -1) {

	    error("too long URL");
	    sock_close(&s);
	    return false;
	}
    }

    if (sock_write(&s, buf, (int)strlen(buf)) == -1) {
	error("socket write failed");
	sock_close(&s);
	return false;
    }

    header = 2;
    c = 0;

    for(;;) {
	len = 0;
	while (len < 100) {
	    if ((i = sock_read(&s, buf + len, sizeof(buf) - len)) == -1) {
		error("socket read failed");
		rv = false;
		goto done;
	    }
	    if (i == 0)
		break;
	    len += i;
	}

	if (len == 0) {
	    rv = !header;
	    break;
	}

	if (header == 2) {
	    if (strncmp(buf, "HTTP", 4)) {
		rv = false;
		break;
	    }
	    i = 0;
	    while (buf[i] != ' ') {
		i++;
		if (i >= len - 1) {
		    rv = false;
		    goto done;
		}
	    }
	    i++;
	    if (buf[i] != '2') {   /* HTTP status code starts with 2 */
		rv = false;
		break;
	    }
	    header = 1;
	}

	printf("#");
	fflush(stdout);

	if (header) {
	    for (i = 0; i < len; i++) {
		if (c % 2 == 0 && buf[i] == '\r')
		    c++;
		else if (c % 2 == 1 && buf[i] == '\n')
		    c++;
		else
		    c = 0;

		if (c == 4) {
		    header = 0;
		    if ((f = fopen(filePath, "wb")) == NULL) {
			error("failed to open %s", filePath);
			rv = false;
			goto done;
		    }
		    if (i < len - 1) {
			n = len - i - 1;
			memmove(buf, buf + i + 1, n);
			len = len - i - 1;
		    } else if (i == len - 1) {
			len = 0;
		    }
		}
	    }
	}

	if (!header && len) {
	    n = len;
	    if (fwrite(buf, 1, n, f) < n) {
		error("file write failed");
		rv =  false;
		break;
	    }
	}
    }
 done:
    printf("\n");
    if (f)
	if (fclose(f) != 0)
	    error("Error closing texture file %s", filePath);
    sock_close(&s);
    return rv;
}

#endif /* HAVE_LIBCURL */


static int Url_parse(const char *urlstr, URL *url)
{
    int len, i, beg, doPort;
    char *buf;

    memset(url, 0, sizeof(URL));
    url->port = 80;
    url->path = "/";

    len = strlen(urlstr);
    buf = strdup(urlstr);
    if (buf == NULL) {
	error("no memory for URL");
	return false;
    }

    for (i = 0; i < len; i++) {
	if (buf[i] == ':') {
	    buf[i] = '\0';
	    url->protocol = buf;
	    break;
	}
    }

    beg = i + 3;
    if (beg >= len || buf[i + 1] != '/' || buf[i + 2] != '/') {
	free(buf);
	return false;
    }

    doPort = 0;
    for (i = beg; i < len; i++) {
	if (buf[i] == ':' || buf[i] == '/') {
	    if (buf[i] == ':') doPort = 1;
	    buf[i] = '\0';
	    break;
	}
    }

    url->host = buf + beg;
    beg = i + 1;
    if (beg >= len) return true;

    if (doPort) {
	for (i = beg; i < len; i++) {
	    if (buf[i] == '/') {
		buf[i] = '\0';
		break;
	    }
	}
	url->port = atoi(buf + beg);
	/* error detection should be added */

	beg = i + 1;
	if (beg >= len)
	    return true;
    }

    /* make space for / in the beginning of path */
    memmove(url->host - 1, url->host, strlen(url->host) + 1);
    url->host--;
    buf[beg - 1] = '/';

    for (i = beg; i < len; i++) {
	if (buf[i] == '?') {
	    buf[i] = '\0';
	    break;
	}
    }
    url->path = buf + beg - 1;

    beg = i + 1;
    if (beg >= len) return true;

    url->query = buf + beg;
    return true;
}


static void Url_free_parsed(URL *url)
{
    free(url->protocol);
}
