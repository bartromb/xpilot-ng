/*
 * XPilotNG/SDL, an SDL/OpenGL XPilot client. Copyright (C) 2003-2004 by 
 *
 *     Juha Lindström <juhal@users.sourceforge.net>
 *     Erik Andersson <deity_at_home.se>
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

#include "sdlinit.h"
#include "sdlkeys.h"
#include "console.h"
#include "sdlpaint.h"
#include "glwidgets.h"
#include "../xhacks.h"

/* TODO: remove these from client.h and put them in *event.h */
bool            initialPointerControl = false;

static int	mouseMovement;	/* horizontal mouse movement. */

GLWidget *clicktarget[NUM_MOUSE_BUTTONS];
GLWidget *hovertarget = NULL;

int Process_event(SDL_Event *evt);

void Platform_specific_pointer_control_set_state(bool on)
{
    assert(clData.pointerControl != on);

    if (on) {
    	MainWidget_ShowMenu(MainWidget, false);
	SDL_SetWindowGrab(MainSDLWindow, SDL_TRUE);
	SDL_ShowCursor(SDL_DISABLE);
    } else {
    	MainWidget_ShowMenu(MainWidget, true);
	SDL_SetWindowGrab(MainSDLWindow, SDL_FALSE);
	SDL_ShowCursor(SDL_ENABLE);
    }
    
#ifdef HAVE_XF86MISC
    {
	SDL_SysWMinfo info;
	SDL_VERSION(&info.version);
	if (SDL_GetWMInfo(&info) > 0)
	    Disable_emulate3buttons(on, info.info.x11.display);
    }
#endif
}

void Platform_specific_talk_set_state(bool on)
{
    assert(clData.talking != on);
    if (on)
	Console_show();
    else
	Console_hide();
}

void Record_toggle(void)
{
    /* TODO: implement if you think it is worth it */
    Add_message("Can't record with this client. [*Client reply*]");
}

void Toggle_radar_and_scorelist(void)
{
    /* TODO */
    return;
}

#ifndef _WINDOWS
extern int videoFlags;
extern SDL_Window *MainSDLWindow;
void Toggle_fullscreen(void)
{
    static int initial_w = -1, initial_h = -1;
    int w, h;

    if (initial_w == -1) {
	initial_w = draw_width;
	initial_h = draw_height;
    }

    if (videoFlags & SDL_WINDOW_FULLSCREEN_DESKTOP) {
	videoFlags &= ~SDL_WINDOW_FULLSCREEN_DESKTOP;
	Resize_Window(initial_w, initial_h);
	return;
    }

    w = initial_w = draw_width;
    h = initial_h = draw_height;

    videoFlags |= SDL_WINDOW_FULLSCREEN_DESKTOP;
    if (Resize_Window(w, h) == 0)
	return;

    videoFlags &= ~SDL_WINDOW_FULLSCREEN_DESKTOP;
    Resize_Window(initial_w, initial_h);
    Add_message("Failed to change video mode. [*Client reply*]");
}
#else
void Toggle_fullscreen(void)
{
    Add_message("Changing mode does not work in Windows. [*Client reply*]");
}
#endif

/*
 * SDL reports mouse coordinates in logical window units, but the widgets are
 * laid out in drawable pixels so that rendering is full-resolution on HiDPI
 * displays. Scale the event in place, once, before anything reads it. Both
 * scales are 1.0 on an ordinary display, so this is a no-op there.
 */
static void Scale_mouse_event(SDL_Event *evt)
{
    if (hidpi_scale_x == 1.0f && hidpi_scale_y == 1.0f)
	return;

    switch (evt->type) {
    case SDL_MOUSEMOTION:
	evt->motion.x    = (Sint32)(evt->motion.x    * hidpi_scale_x);
	evt->motion.y    = (Sint32)(evt->motion.y    * hidpi_scale_y);
	evt->motion.xrel = (Sint32)(evt->motion.xrel * hidpi_scale_x);
	evt->motion.yrel = (Sint32)(evt->motion.yrel * hidpi_scale_y);
	break;
    case SDL_MOUSEBUTTONDOWN:
    case SDL_MOUSEBUTTONUP:
	evt->button.x = (Sint32)(evt->button.x * hidpi_scale_x);
	evt->button.y = (Sint32)(evt->button.y * hidpi_scale_y);
	break;
    default:
	break;
    }
}

int Process_event(SDL_Event *evt)
{
    int button;

    mouseMovement = 0;

    Scale_mouse_event(evt);

    if (Console_process(evt)) return 1;
    
    switch (evt->type) {
	
    case SDL_QUIT:
	Client_exit(0);
	break;
	
    case SDL_KEYDOWN:
	if (Console_isVisible()) break;
	Keyboard_button_pressed((xp_keysym_t)evt->key.keysym.sym);
	break;
	
    case SDL_KEYUP:
        /* letting release events through to prevent some keys from locking */
	/*if (Console_isVisible()) break;*/
	Keyboard_button_released((xp_keysym_t)evt->key.keysym.sym);
	break;
	
    case SDL_MOUSEBUTTONDOWN:
	button = evt->button.button;
	if (!clData.pointerControl) {
	    if ( (clicktarget[button-1] = FindGLWidget(MainWidget,evt->button.x,evt->button.y)) ) {
	    	if (clicktarget[button-1]->button) {
		    clicktarget[button-1]->button(button,evt->button.state,
		    	    	    	    evt->button.x,evt->button.y,
					    clicktarget[button-1]->buttondata);
		}
	    }
	    
	} else {
	    Pointer_button_pressed(button);
	}
	break;
	
    case SDL_MOUSEMOTION:
	if (clData.pointerControl) {
	    mouseMovement += evt->motion.xrel;
	} else {
	    /*xpprintf("mouse motion xrel=%i yrel=%i\n",evt->motion.xrel,evt->motion.yrel);*/
	    /*for (i = 0;i<NUM_MOUSE_BUTTONS;++i)*/ /* dragdrop for all mouse buttons*/
	    if (clicktarget[0]) { /*is button one pressed?*/
	    	/*xpprintf("SDL_MOUSEBUTTONDOWN drag: area found!\n");*/
	    	if (clicktarget[0]->motion) {
		    clicktarget[0]->motion(evt->motion.xrel,evt->motion.yrel,
		    	    	    	evt->button.x,evt->button.y,
					clicktarget[0]->motiondata);
		}
	    } else {
    	    	GLWidget *tmp = FindGLWidget(MainWidget,evt->button.x,evt->button.y);
		if (tmp != hovertarget) {
    	    	    if (hovertarget && hovertarget->hover) {
		    	hovertarget->hover(false,evt->button.x,evt->button.y,hovertarget->hoverdata);
		    }
		    tmp = FindGLWidget(MainWidget,evt->button.x,evt->button.y);
		    if (tmp && tmp->hover)
    	    	    	tmp->hover(true,evt->button.x,evt->button.y,tmp->hoverdata);
		    hovertarget = tmp;
		}
	    }
	}
	break;
	
    case SDL_MOUSEBUTTONUP:
	button = evt->button.button;
	if (clData.pointerControl) {
	    Pointer_button_released(button);
	} else {
	    if ( clicktarget[button-1] ) {
	    	if (clicktarget[button-1]->button) {
		    clicktarget[button-1]->button(button,evt->button.state,
		    	    	    	    	evt->button.x,evt->button.y,
						clicktarget[button-1]->buttondata);
		}
		clicktarget[button-1] = NULL;
	    }
	}
	break;

    case SDL_WINDOWEVENT:
	/* SDL 1.2's VIDEORESIZE and VIDEOEXPOSE both fold into WINDOWEVENT.
	 * SIZE_CHANGED covers programmatic resizes as well as user ones. */
	if (evt->window.event == SDL_WINDOWEVENT_SIZE_CHANGED
	    || evt->window.event == SDL_WINDOWEVENT_RESIZED)
	    Resize_Window(evt->window.data1, evt->window.data2);
	break;

    default:
      break;
    }
    
    if (mouseMovement) {
	Client_pointer_move(mouseMovement);
	Net_flush();
    }
    return 1;
}

/* kps - just here so that this can link to generic client files */
void Config_redraw(void)
{

}
