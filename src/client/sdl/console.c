/*
 * XPilotNG/SDL, an SDL/OpenGL XPilot client.
 *
 * Copyright (C) 2003-2004 Juha Lindström <juhal@users.sourceforge.net>
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

#include "xpclient_sdl.h"

#include "console.h"
#include "SDL_console.h"
#include "sdlwindow.h"

static sdl_window_t console_window;
static ConsoleInformation *console;

void command_handler(ConsoleInformation *, char *);

static void Console_refresh(void)
{
    SDL_FillRect(console_window.surface, NULL, 0);
    CON_UpdateConsole(console);
    CON_DrawConsole(console);
    sdl_window_refresh(&console_window);
}

int Console_init(void)
{
    SDL_Rect cr;
    cr.w = 500;
    cr.h = 100;
    if (cr.w > draw_width) cr.w = draw_width;
    if (cr.h > draw_height) cr.h = draw_height;
    cr.x = (draw_width - cr.w) / 2;
    cr.y = (draw_height - cr.h) / 2;

    if (sdl_window_init(&console_window, cr.x, cr.y, cr.w, cr.h)) {
	error("failed to init console window");
	return -1;
    }
    
    console = CON_Init(CONF_FONTDIR "ConsoleFont.bmp", console_window.surface, 100, cr);
    if (console == NULL) {
	error("failed to init SDL_console");
	sdl_window_destroy(&console_window);
	return -1;
    }
    CON_SetExecuteFunction(console, command_handler);
    CON_Topmost(console);
    CON_Alpha(console, 200);
    CON_SetPrompt(console, "xp> ");
    Console_print("XPilot console ready");
    /*Console_print("Type /help to get help on commands.");
    Console_show();*/
    return 0;
}

void Console_paint(void)
{
    if (!Console_isVisible()) return;
    if (console->Visible != CON_OPEN) Console_refresh();
    console_window.x = (draw_width - console_window.w) / 2;
    console_window.y = (draw_height - console_window.h) / 2;
    sdl_window_paint(&console_window);
    glBegin(GL_LINE_LOOP);
    glColor4ub(0, 0, 0, 0xff);
    glVertex2i(console_window.x, console_window.y + console_window.h + 2);    
    glColor4ub(0, 0x90, 0x00, 0xff);
    glVertex2i(console_window.x, console_window.y);
    glColor4ub(0, 0, 0, 0xff);
    glVertex2i(console_window.x + console_window.w, console_window.y);
    glColor4ub(0, 0x90, 0x00, 0xff);
    glVertex2i(console_window.x + console_window.w, 
	       console_window.y + console_window.h + 2);
    glEnd();
}

void Console_show(void)
{
    CON_Show(console);
    Console_refresh();
}

void Console_hide(void)
{
    CON_Hide(console);
}

int Console_isVisible(void)
{
    return (console->Visible != CON_CLOSED);
}

int Console_process(SDL_Event *e)
{
    if (CON_Events(e) == NULL) {
	Console_refresh();
	return 1;
    }
    return 0;
}

void Paste_String_to_Console(char *text)
{
    Add_String_to_Console(text);
    Console_refresh();
}

void Console_cleanup(void)
{
    CON_Destroy(console);
    sdl_window_destroy(&console_window);
}

void Console_print(const char *str, ...)
{
    char buf[1024];
    va_list marker;

    /*
     * CON_Out is itself variadic, so passing the va_list to it as an ordinary
     * argument made it read the va_list object as the first format argument.
     * That crashed on the first %s. Format here and hand CON_Out a plain
     * string instead. Every previous caller passed no format arguments, which
     * is why this went unnoticed.
     */
    va_start(marker, str);
    vsnprintf(buf, sizeof(buf), str, marker);
    va_end(marker);

    CON_Out(console, "%s", buf);
    Console_refresh();
}

/*
 * In-client key remapping.
 *
 * Anything not starting with '/' is chat, exactly as before. The commands
 * exist so bindings can be changed without leaving the game and editing
 * xpilotrc by hand; they deliberately do not change any default binding.
 */

static void Console_list_keys(const char *filter)
{
    int i, shown = 0;

    for (i = 0; i < num_options; i++) {
	xp_option_t *opt = &options[i];

	if (opt->type != xp_key_option)
	    continue;
	if (filter != NULL && strstr(opt->name, filter) == NULL)
	    continue;

	Console_print("%-24s %s", opt->name,
		      (opt->key_string != NULL && opt->key_string[0] != '\0')
		      ? opt->key_string : "(unbound)");
	shown++;
    }

    if (shown == 0)
	Console_print("No key options%s%s.",
		      filter ? " matching " : "", filter ? filter : "");
    else
	Console_print("%d key option%s.", shown, shown == 1 ? "" : "s");
}

static void Console_bind(char *args)
{
    char *name, *value;
    xp_option_t *opt;

    name = strtok(args, " \t");
    if (name == NULL) {
	Console_list_keys(NULL);
	return;
    }

    value = strtok(NULL, "");
    if (value == NULL) {
	/* One argument: show this binding rather than guessing at intent. */
	opt = Find_option(name);
	if (opt == NULL || opt->type != xp_key_option) {
	    Console_print("No key option named '%s'.", name);
	    return;
	}
	Console_print("%-24s %s", opt->name,
		      (opt->key_string != NULL && opt->key_string[0] != '\0')
		      ? opt->key_string : "(unbound)");
	return;
    }

    while (*value == ' ' || *value == '\t')
	value++;

    opt = Find_option(name);
    if (opt == NULL || opt->type != xp_key_option) {
	Console_print("No key option named '%s'. Try /keys to list them.",
		      name);
	return;
    }

    if (!Set_option(name, value, xp_option_origin_config)) {
	Console_print("Could not bind %s to '%s'.", name, value);
	return;
    }

    Console_print("%s is now bound to %s.", name, value);
    Console_print("Use /save to keep this for next time.");
}

static void Console_save(void)
{
    char path[PATH_MAX];

    Xpilotrc_get_filename(path, sizeof(path));
    if (path[0] == '\0') {
	Console_print("Could not work out where to save the config.");
	return;
    }

    if (Xpilotrc_write(path) != 0) {
	Console_print("Failed to write %s.", path);
	return;
    }
    Console_print("Saved to %s.", path);
}

static void Console_help(void)
{
    Console_print("/keys [text]         list key bindings, optionally filtered");
    Console_print("/bind <option> <key> bind a key, e.g. /bind keyFireShot space");
    Console_print("/bind <option> none  unbind");
    Console_print("/save                write the config file");
    Console_print("/help                this list");
    Console_print("Anything else is sent as chat.");
}

void command_handler(ConsoleInformation *con, char *command)
{
    char buf[512];
    char *word, *rest;

    if (command == NULL || command[0] != '/') {
	Net_talk(command);
	Talk_set_state(false);
	return;
    }

    strlcpy(buf, command + 1, sizeof(buf));
    word = strtok(buf, " \t");
    rest = strtok(NULL, "");

    if (word == NULL) {
	Console_help();
	return;
    }

    if (!strcasecmp(word, "help"))
	Console_help();
    else if (!strcasecmp(word, "keys"))
	Console_list_keys(rest);
    else if (!strcasecmp(word, "bind"))
	Console_bind(rest != NULL ? rest : (char *)"");
    else if (!strcasecmp(word, "save"))
	Console_save();
    else
	Console_print("Unknown command '/%s'. Try /help.", word);
}
