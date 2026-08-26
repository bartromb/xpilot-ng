/*
 * XPilotNG/SDL, an SDL/OpenGL XPilot client. Copyright (C) 2003-2004 by 
 *
 *      Juha Lindstr�m       <juhal@users.sourceforge.net>
 *      Erik Andersson       <deity_at_home.se>
 *      Darel Cullen         <darelcullen@users.sourceforge.net>
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

#include "text.h"
#include "console.h"
#include "sdlkeys.h"
#include "glwidgets.h"
#include "sdlpaint.h"
#include "sdlinit.h"

/* These are only needed for the polygon tessellation */
/* I'd like to move them to Paint_init/cleanup but because it */
/* is called before the map is ready I need separate functions */
/* for now.. */
extern int Gui_init(void);
extern void Gui_cleanup(void);

int draw_depth;

/* Flags to pass to SDL_CreateWindow */
int videoFlags;

/* The window and its GL context. Under SDL2 there is no display surface for
 * an OpenGL window, so MainSDLSurface is gone; MainSDLWindow being non-NULL
 * is what now signals "the window exists". */
SDL_Window *MainSDLWindow = NULL;
SDL_GLContext MainGLContext = NULL;

/*
 * Ratio of drawable pixels to logical window units. 1.0 on an ordinary
 * display; 2.0 on a typical HiDPI one. draw_width/draw_height are kept in
 * drawable pixels so everything renders at full resolution, which means mouse
 * coordinates — which SDL reports in logical units — have to be scaled up
 * before they are tested against widget bounds. See Scale_mouse_event().
 */
float hidpi_scale_x = 1.0f;
float hidpi_scale_y = 1.0f;

/*
 * Refresh draw_width/draw_height from the window's actual drawable size.
 * On a non-HiDPI display this is just the window size and the scales stay 1.
 */
void Update_drawable_size(void)
{
    int dw = 0, dh = 0, ww = 0, wh = 0;

    if (MainSDLWindow == NULL)
	return;

    SDL_GL_GetDrawableSize(MainSDLWindow, &dw, &dh);
    SDL_GetWindowSize(MainSDLWindow, &ww, &wh);
    if (dw <= 0 || dh <= 0 || ww <= 0 || wh <= 0)
	return;

    draw_width = dw;
    draw_height = dh;
    hidpi_scale_x = (float)dw / (float)ww;
    hidpi_scale_y = (float)dh / (float)wh;
}

font_data gamefont;
font_data mapfont;
int gameFontSize;
int mapFontSize;
char *gamefontname;

/* ugly kps hack */
static bool file_exists(const char *path) 
{ 
  FILE *fp;

  if (!path) {
    return false; 
  } else {
    fp = fopen(path ? path : "", "r");
    if (fp) { 
      fclose(fp); 
      return true;
    }
    return false; 
  }
}

int Init_playing_windows(void)
{
    /*
    sdl_init_colors();
    Init_spark_colors();
    */
    if ( !AppendGLWidgetList(&MainWidget,Init_MainWidget(&gamefont)) ) {
	error("widget initialization failed");
	return -1;
    }
    if (Console_init()) {
	error("console initialization failed");
	return -1;
    }
    if (Gui_init()) {
	error("gui initialization failed");
	return -1;
    }

    return 0;
}

static bool find_size(int *w, int *h)
{
    SDL_DisplayMode mode, best;
    int i, d, n, best_d;

    n = SDL_GetNumDisplayModes(0);
    if (n < 1) return false;

    best_d = INT_MAX;
    best = (SDL_DisplayMode){0};
    for (i = 0; i < n; i++) {
	if (SDL_GetDisplayMode(0, i, &mode) != 0) continue;
	d = (mode.w - *w)*(mode.w - *w) + (mode.h - *h)*(mode.h - *h);
	if (d < best_d) {
	    best_d = d;
	    best = mode;
	}
    }
    if (best_d == INT_MAX) return false;
    *w = best.w;
    *h = best.h;
    return true;
}

int Init_window(void)
{
    int value;
    char defaultfontname[] = CONF_FONTDIR "FreeSansBoldOblique.ttf";
    bool gf_exists = true,df_exists = true,gf_init = false, mf_init = false;
    
    if (TTF_Init()) {
    	error("SDL_ttf initialization failed: %s", SDL_GetError());
    	return -1;
    }
    warn("SDL_ttf initialized.\n");

    Conf_print();

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_NOPARACHUTE) < 0) {
        error("failed to initialize SDL: %s", SDL_GetError());
        return -1;
    }

    atexit(SDL_Quit);

    num_spark_colors=8;

    /* The SDL 1.2 hardware-surface flags (HWSURFACE, HWPALETTE, HWACCEL) and
     * the hw_available/blit_hw probes behind them do not exist in SDL2 and
     * had no effect on an OpenGL window anyway. */
    videoFlags = SDL_WINDOW_OPENGL | SDL_WINDOW_ALLOW_HIGHDPI;
#ifndef _WINDOWS
    videoFlags |= SDL_WINDOW_RESIZABLE;
#else
    videoFlags |= SDL_WINDOW_FULLSCREEN_DESKTOP;
#endif

    {
	SDL_DisplayMode dm;
	if (SDL_GetCurrentDisplayMode(0, &dm) == 0)
	    draw_depth = SDL_BITSPERPIXEL(dm.format);
	else
	    draw_depth = 24;
    }

    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);

    if (videoFlags & SDL_WINDOW_FULLSCREEN_DESKTOP)
      if (!find_size((int*)&draw_width, (int*)&draw_height))
      	videoFlags &= ~SDL_WINDOW_FULLSCREEN_DESKTOP;

    MainSDLWindow = SDL_CreateWindow(TITLE,
				     SDL_WINDOWPOS_CENTERED,
				     SDL_WINDOWPOS_CENTERED,
				     draw_width, draw_height,
				     videoFlags);
    if (MainSDLWindow == NULL) {
	error("Could not create a window: %s", SDL_GetError());
	return -1;
    }

    MainGLContext = SDL_GL_CreateContext(MainSDLWindow);
    if (MainGLContext == NULL) {
	error("Could not create an OpenGL context: %s", SDL_GetError());
	return -1;
    }

    /* The window was created at a logical size; from here on draw_width and
     * draw_height are drawable pixels. */
    Update_drawable_size();

    SDL_GL_GetAttribute(SDL_GL_RED_SIZE, &value);
    printf("RGB bpp %d/", value);
    SDL_GL_GetAttribute(SDL_GL_GREEN_SIZE,&value);
    printf("%d/", value);
    SDL_GL_GetAttribute(SDL_GL_BLUE_SIZE, &value);
    printf("%d ", value);
    SDL_GL_GetAttribute(SDL_GL_DEPTH_SIZE, &value);
    printf("Bit Depth is %d\n",value);

    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glViewport(0, 0, draw_width, draw_height);
    glMatrixMode(GL_PROJECTION);
    gluOrtho2D(0, draw_width, 0, draw_height);
    glMatrixMode(GL_MODELVIEW);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    /* this prevents a freetype crash if you pass non existant fonts */
    if (!file_exists(gamefontname)) {
    	error("cannot find your game font '%s'.\n" \
            "Please check that it exists!",gamefontname);
    	xpprintf("Reverting to defaultfont '%s'\n",defaultfontname);
    	gf_exists = false;
    }
    if (!file_exists(defaultfontname)) {
    	error("cannot find the default font! '%s'" ,defaultfontname);
	df_exists = false;
    }
    
    if (!gf_exists && !df_exists) {
    	error("Failed to find any font files!\n" \
	    	"Probably you forgot to run 'make install',use '-TTFont <font.ttf>' argument" \
		" until you do");
	return -1;
    }
      
    if (gf_exists) {
    	if (fontinit(&gamefont,gamefontname,gameFontSize)) {
    	    error("Font initialization failed with %s", gamefontname);
	} else gf_init = true;
    }
    if (!gf_init && df_exists) {
    	if (fontinit(&gamefont,defaultfontname,gameFontSize)) {
    	    error("Default font initialization failed with %s", defaultfontname);
    	} else gf_init = true;
    }
    
    if (!gf_init) {
    	error("Failed to initialize any game font! (quitting)");
	return -1;
    }
    
    if (gf_exists) {
    	if (fontinit(&mapfont,gamefontname,mapFontSize)) {
    	    error("Font initialization failed with %s", gamefontname);
	} else mf_init = true;
    }
    if (!mf_init && df_exists) {
    	if (fontinit(&mapfont,defaultfontname,mapFontSize)) {
    	    error("Default font initialization failed with %s", defaultfontname);
    	} else mf_init = true;
    }

    if (!mf_init) {
    	error("Failed to initialize any map font! (quitting)");
	return -1;
    }

    return 0;
}

/* function to reset our viewport after a window resize */
int Resize_Window( int width, int height )
{
    SDL_Rect b = {0,0,0,0};

	if (videoFlags & SDL_WINDOW_FULLSCREEN_DESKTOP)
		if (!find_size(&width, &height))
			return -1;
    
    if (MainSDLWindow == NULL)
	return -1;

    if (SDL_SetWindowFullscreen(MainSDLWindow,
	    videoFlags & SDL_WINDOW_FULLSCREEN_DESKTOP) != 0)
	return -1;

    /* Only resize explicitly when windowed; in fullscreen-desktop the window
     * follows the display and setting a size fights it. */
    if (!(videoFlags & SDL_WINDOW_FULLSCREEN_DESKTOP))
	SDL_SetWindowSize(MainSDLWindow, width, height);

    /* width/height are logical units; the drawable can be larger on HiDPI, so
     * lay the widgets out against the drawable size rather than the request. */
    Update_drawable_size();

    b.w = draw_width;
    b.h = draw_height;

    SetBounds_GLWidget(MainWidget,&b);
    

    /* change to the projection matrix and set our viewing volume. */
    glMatrixMode( GL_PROJECTION );

    glLoadIdentity( );

    gluOrtho2D(0, draw_width, 0, draw_height);
    
    /* Make sure we're chaning the model view and not the projection */
    glMatrixMode( GL_MODELVIEW );
    
    /* Reset The View */
    glLoadIdentity( );

    /* Setup our viewport. */
    glViewport( 0, 0, ( GLint )draw_width, ( GLint )draw_height );
    return 0;
}


void Platform_specific_cleanup(void)
{
    Close_Widget(&MainWidget);
    Gui_cleanup();
    Console_cleanup();
    fontclean(&gamefont);
    fontclean(&mapfont);
    TTF_Quit();
    SDL_Quit();
}

static bool Set_geometry(xp_option_t *opt, const char *s)
{
    int w = 0, h = 0;

    if (s[0] == '=') {
	sscanf(s, "%*c%d%*c%d", &w, &h);
    } else {
	sscanf(s, "%d%*c%d", &w, &h);
    }
    if (w == 0 || h == 0) return false;
    if (MainSDLWindow != NULL) {
	Resize_Window(w, h);
    } else {
	draw_width = w;
	draw_height = h;
    }
    return true;
}

static const char* Get_geometry(xp_option_t *opt)
{
    static char buf[20]; /* should be enough */
    snprintf(buf, 20, "%dx%d", draw_width, draw_height);
    return buf;
}

static bool Set_fontName(xp_option_t *opt, const char *value)
{
    UNUSED_PARAM(opt);
    XFREE(gamefontname);
    gamefontname = xp_safe_strdup(value);

    return true;
}

static const char *Get_fontName(xp_option_t *opt)
{
    UNUSED_PARAM(opt);
    return gamefontname;
}

static xp_option_t sdlinit_options[] = {
    XP_STRING_OPTION(
	"geometry",
	"1280x1024",
	NULL,
	0,
	Set_geometry, NULL, Get_geometry,
	XP_OPTFLAG_DEFAULT,
	"Set the initial window geometry.\n"),
    
     XP_INT_OPTION(
        "gameFontSize",
	16, 12, 32,
	&gameFontSize,
	NULL,
	XP_OPTFLAG_DEFAULT,
	"Height of font used for game strings.\n"),

    XP_INT_OPTION(
        "mapFontSize",
	16, 12, 64,
	&mapFontSize,
	NULL,
	XP_OPTFLAG_DEFAULT,
	"Height of font used for strings painted on the map.\n"),

    XP_STRING_OPTION(
	"TTFont",
	CONF_FONTDIR "FreeSansBoldOblique.ttf",
	NULL, 0,
	Set_fontName, NULL, Get_fontName,
	XP_OPTFLAG_DEFAULT,
	"Set the font to use.\n")
};

void Store_sdlinit_options(void)
{
    STORE_OPTIONS(sdlinit_options);
}
