/* 
 * XPilot NG, a multiplayer space war game.
 *
 * Copyright (C) 1991-2001 by
 *
 *      Bjørn Stabell        <bjoern@xpilot.org>
 *      Ken Ronny Schouten   <ken@xpilot.org>
 *      Bert Gijsbers        <bert@xpilot.org>
 *      Dick Balaska         <dick@xpilot.org>
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

#include "xpcommon.h"

#ifdef __APPLE__
# include <mach-o/dyld.h>
#endif

/*
 * Portable builds -- the Windows zip and installer, the macOS app bundle --
 * compile a relative CONF_DATADIR ("lib/"), so the game finds its maps,
 * textures, fonts and sounds through the working directory. That works when
 * it is started from its own folder and fails every other way it can be
 * started: a Start Menu shortcut, a Finder double-click, or a shell sitting
 * anywhere else all leave the process somewhere the data is not, and the game
 * comes up with nothing loaded.
 *
 * Anchor the working directory to the executable instead. Builds installed
 * under an absolute prefix (the Linux packages) compile an absolute
 * CONF_DATADIR and are left alone.
 */

static bool Conf_datadir_is_absolute(void)
{
    const char *d = CONF_DATADIR;

    if (d[0] == '/')
	return true;
#ifdef _WINDOWS
    if (d[0] != '\0' && d[1] == ':')
	return true;
    if (d[0] == '\\')		/* UNC path */
	return true;
#endif
    return false;
}

/* Full path of the running executable, or false if the platform will not say. */
static bool Conf_executable_path(char *buf, size_t size)
{
#if defined(_WINDOWS)
    DWORD n = GetModuleFileName(NULL, buf, (DWORD)size);

    return (n > 0 && n < size);
#elif defined(__APPLE__)
    uint32_t n = (uint32_t)size;

    return (_NSGetExecutablePath(buf, &n) == 0);
#else
    ssize_t n = readlink("/proc/self/exe", buf, size - 1);

    if (n <= 0)
	return false;
    buf[n] = '\0';
    return true;
#endif
}

static bool Conf_has_datadir(const char *dir)
{
    char path[1024];

    if (snprintf(path, sizeof path, "%s%c%s", dir, PATHNAME_SEP, CONF_DATADIR)
	>= (int)sizeof path)
	return false;

    return (access(path, R_OK) == 0);
}

void Conf_anchor_datadir(void)
{
    char exe[1024], dir[1024];
    char *p;

    if (Conf_datadir_is_absolute())
	return;

    if (!Conf_executable_path(exe, sizeof exe))
	return;

    strlcpy(dir, exe, sizeof dir);
    p = strrchr(dir, PATHNAME_SEP);
#ifdef _WINDOWS
    if (p == NULL)
	p = strrchr(dir, '/');
#endif
    if (p == NULL)
	return;
    *p = '\0';

    /* Next to the executable: the zip, the installed Windows program. */
    if (Conf_has_datadir(dir)) {
	if (chdir(dir) != 0)
	    warn("could not change to the data directory %s", dir);
	return;
    }

    /* Inside a macOS bundle the executable is in Contents/MacOS and the data
     * is beside it in Contents/Resources. */
    {
	char res[1024];

	if (snprintf(res, sizeof res, "%s%c..%cResources", dir,
		     PATHNAME_SEP, PATHNAME_SEP) < (int)sizeof res
	    && Conf_has_datadir(res)) {
	    if (chdir(res) != 0)
		warn("could not change to the data directory %s", res);
	    return;
	}
    }

    /* Nothing found: leave the working directory alone, so running from a
     * source tree still works. */
}


char *Conf_datadir(void)
{
    static char conf[] = CONF_DATADIR;

    return conf;
}

char *Conf_defaults_file_name(void)
{
    static char conf[] = CONF_DEFAULTS_FILE_NAME;

    return conf;
}

char *Conf_password_file_name(void)
{
    static char conf[] = CONF_PASSWORD_FILE_NAME;

    return conf;
}

#if 0
char *Conf_player_passwords_file_name(void)
{
    static char conf[] = CONF_PLAYER_PASSWORDS_FILE_NAME;

    return conf;
}
#endif

char *Conf_mapdir(void)
{
    static char conf[] = CONF_MAPDIR;

    return conf;
}

char *Conf_fontdir(void)
{
    static char conf[] = CONF_FONTDIR;

    return conf;
}

char *Conf_default_map(void)
{
    static char conf[] = CONF_DEFAULT_MAP;

    return conf;
}

char *Conf_servermotdfile(void)
{
    static char conf[] = CONF_SERVERMOTDFILE;
    static char env[] = "XPILOTSERVERMOTD";
    char *filename;

    filename = getenv(env);
    if (filename == NULL)
	filename = conf;

    return filename;
}

char *Conf_localmotdfile(void)
{
    static char conf[] = CONF_LOCALMOTDFILE;

    return conf;
}

char conf_logfile_string[] = CONF_LOGFILE;

char *Conf_logfile(void)
{
    return conf_logfile_string;
}

char *Conf_ship_file(void)
{
    static char conf[] = CONF_SHIP_FILE;

    return conf;
}

char *Conf_texturedir(void)
{
    static char conf[] = CONF_TEXTUREDIR;

    return conf;
}

char *Conf_localguru(void)
{
    static char conf[] = CONF_LOCALGURU;

    return conf;
}

char *Conf_robotfile(void)
{
    static char conf[] = CONF_ROBOTFILE;

    return conf;
}

char *Conf_zcat_ext(void)
{
    static char conf[] = CONF_ZCAT_EXT;

    return conf;
}

char *Conf_zcat_format(void)
{
    static char conf[] = CONF_ZCAT_FORMAT;

    return conf;
}

char *Conf_sounddir(void)
{
    static char conf[] = CONF_SOUNDDIR;

    return conf;
}

char *Conf_soundfile(void)
{
    static char conf[] = CONF_SOUNDFILE;

    return conf;
}


void Conf_print(void)
{
    warn("============================================================");
    warn("VERSION                   = %s", VERSION);
    warn("PACKAGE                   = %s", PACKAGE);

#ifdef DBE
    warn("DBE");
#endif
#ifdef MBX
    warn("MBX");
#endif
#ifdef PLOCKSERVER
    warn("PLOCKSERVER");
#endif
#ifdef DEVELOPMENT
    warn("DEVELOPMENT");
#endif

    warn("Conf_localguru()          = %s", Conf_localguru());
    warn("Conf_datadir()            = %s", Conf_datadir());
    warn("Conf_defaults_file_name() = %s", Conf_defaults_file_name());
    warn("Conf_password_file_name() = %s", Conf_password_file_name());
    warn("Conf_mapdir()             = %s", Conf_mapdir());
    warn("Conf_default_map()        = %s", Conf_default_map());
    warn("Conf_servermotdfile()     = %s", Conf_servermotdfile());
    warn("Conf_robotfile()          = %s", Conf_robotfile());
    warn("Conf_logfile()            = %s", Conf_logfile());
    warn("Conf_localmotdfile()      = %s", Conf_localmotdfile());
    warn("Conf_ship_file()          = %s", Conf_ship_file());
    warn("Conf_texturedir()         = %s", Conf_texturedir());
    warn("Conf_fontdir()            = %s", Conf_fontdir());
    warn("Conf_sounddir()           = %s", Conf_sounddir());
    warn("Conf_soundfile()          = %s", Conf_soundfile());
    warn("Conf_zcat_ext()           = %s", Conf_zcat_ext());
    warn("Conf_zcat_format()        = %s", Conf_zcat_format());
    warn("============================================================");
}
