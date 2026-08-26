/*
 * XPilot NG, a multiplayer space war game.
 *
 * Gamepad support via the SDL2 GameController API.
 *
 * The mapping from controller inputs to game actions is deliberately kept in
 * pure functions (Gamepad_button_action, Gamepad_axis_action) with no SDL
 * state and no side effects, so it can be tested without a controller
 * attached. Everything that touches SDL or game state lives in the handlers
 * below.
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
#include "gamepad.h"

/*
 * Default button mapping. Chosen to match how the keyboard defaults play:
 * thrust and fire are the two things a hand rests on, shields sit next to
 * them, and the shoulder buttons turn.
 *
 * SDL's names are positional, not label-based: SDL_CONTROLLER_BUTTON_A is
 * always the bottom face button whatever the pad prints on it.
 */
keys_t Gamepad_button_action(int button)
{
    switch (button) {
    case SDL_CONTROLLER_BUTTON_A:		return KEY_THRUST;
    case SDL_CONTROLLER_BUTTON_B:		return KEY_FIRE_SHOT;
    case SDL_CONTROLLER_BUTTON_X:		return KEY_SHIELD;
    case SDL_CONTROLLER_BUTTON_Y:		return KEY_FIRE_MISSILE;
    case SDL_CONTROLLER_BUTTON_LEFTSHOULDER:	return KEY_TURN_LEFT;
    case SDL_CONTROLLER_BUTTON_RIGHTSHOULDER:	return KEY_TURN_RIGHT;
    case SDL_CONTROLLER_BUTTON_BACK:		return KEY_TOGGLE_VELOCITY;
    case SDL_CONTROLLER_BUTTON_START:		return KEY_PAUSE;
    case SDL_CONTROLLER_BUTTON_LEFTSTICK:	return KEY_CLOAK;
    case SDL_CONTROLLER_BUTTON_RIGHTSTICK:	return KEY_REFUEL;
    case SDL_CONTROLLER_BUTTON_DPAD_UP:		return KEY_LOCK_NEXT;
    case SDL_CONTROLLER_BUTTON_DPAD_DOWN:	return KEY_LOCK_PREV;
    case SDL_CONTROLLER_BUTTON_DPAD_LEFT:	return KEY_TURN_LEFT;
    case SDL_CONTROLLER_BUTTON_DPAD_RIGHT:	return KEY_TURN_RIGHT;
    default:					return KEY_DUMMY;
    }
}

/*
 * Map an axis to an action plus whether it should currently be held.
 *
 * Sticks are bidirectional, so each axis yields a different action depending
 * on sign; triggers rest at 0 and only travel positive. Returns KEY_DUMMY for
 * axes that are not bound, and reports through *held whether the axis is
 * currently past the dead zone.
 *
 * The dead zone matters more than it looks: without one, stick drift on a
 * worn controller holds a turn key down permanently.
 */
keys_t Gamepad_axis_action(int axis, int value, bool *held)
{
    bool past = (value > GAMEPAD_DEADZONE) || (value < -GAMEPAD_DEADZONE);

    switch (axis) {
    case SDL_CONTROLLER_AXIS_LEFTX:
	*held = past;
	return (value < 0) ? KEY_TURN_LEFT : KEY_TURN_RIGHT;
    case SDL_CONTROLLER_AXIS_TRIGGERRIGHT:
	*held = (value > GAMEPAD_DEADZONE);
	return KEY_THRUST;
    case SDL_CONTROLLER_AXIS_TRIGGERLEFT:
	*held = (value > GAMEPAD_DEADZONE);
	return KEY_SHIELD;
    default:
	*held = false;
	return KEY_DUMMY;
    }
}

#ifndef GAMEPAD_MAPPING_TEST

static SDL_GameController *gamepad = NULL;

/*
 * Remember which action each axis is currently holding, so that crossing the
 * centre releases the old direction before pressing the new one. Without this
 * a quick left-to-right flick leaves KEY_TURN_LEFT stuck down.
 */
static keys_t axis_held[SDL_CONTROLLER_AXIS_MAX];

void Gamepad_init(void)
{
    int i;

    for (i = 0; i < SDL_CONTROLLER_AXIS_MAX; i++)
	axis_held[i] = KEY_DUMMY;

    if (SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) != 0) {
	warn("Gamepad support unavailable: %s", SDL_GetError());
	return;
    }

    /* Open the first controller present; hotplug is handled by events. */
    for (i = 0; i < SDL_NumJoysticks(); i++) {
	if (!SDL_IsGameController(i))
	    continue;
	gamepad = SDL_GameControllerOpen(i);
	if (gamepad != NULL) {
	    xpinfo("Using gamepad: %s", SDL_GameControllerName(gamepad));
	    break;
	}
    }
}

void Gamepad_cleanup(void)
{
    if (gamepad != NULL) {
	SDL_GameControllerClose(gamepad);
	gamepad = NULL;
    }
}

/*
 * Handle a controller event. Returns true if the event was consumed.
 */
bool Gamepad_process(SDL_Event *evt)
{
    keys_t key;
    bool held;

    switch (evt->type) {

    case SDL_CONTROLLERDEVICEADDED:
	if (gamepad == NULL && SDL_IsGameController(evt->cdevice.which)) {
	    gamepad = SDL_GameControllerOpen(evt->cdevice.which);
	    if (gamepad != NULL)
		xpinfo("Gamepad connected: %s",
		       SDL_GameControllerName(gamepad));
	}
	return true;

    case SDL_CONTROLLERDEVICEREMOVED:
	if (gamepad != NULL
	    && evt->cdevice.which
	       == SDL_JoystickInstanceID(
		      SDL_GameControllerGetJoystick(gamepad))) {
	    /* Release anything the pad was holding, or the ship keeps
	     * thrusting after the cable is pulled. */
	    int i;
	    for (i = 0; i < SDL_CONTROLLER_AXIS_MAX; i++) {
		if (axis_held[i] != KEY_DUMMY) {
		    Key_release(axis_held[i]);
		    axis_held[i] = KEY_DUMMY;
		}
	    }
	    SDL_GameControllerClose(gamepad);
	    gamepad = NULL;
	    xpinfo("Gamepad disconnected.");
	}
	return true;

    case SDL_CONTROLLERBUTTONDOWN:
	key = Gamepad_button_action(evt->cbutton.button);
	if (key != KEY_DUMMY)
	    Key_press(key);
	return true;

    case SDL_CONTROLLERBUTTONUP:
	key = Gamepad_button_action(evt->cbutton.button);
	if (key != KEY_DUMMY)
	    Key_release(key);
	return true;

    case SDL_CONTROLLERAXISMOTION:
	if (evt->caxis.axis >= SDL_CONTROLLER_AXIS_MAX)
	    return true;
	key = Gamepad_axis_action(evt->caxis.axis, evt->caxis.value, &held);
	if (key == KEY_DUMMY)
	    return true;

	if (!held) {
	    if (axis_held[evt->caxis.axis] != KEY_DUMMY) {
		Key_release(axis_held[evt->caxis.axis]);
		axis_held[evt->caxis.axis] = KEY_DUMMY;
	    }
	} else if (axis_held[evt->caxis.axis] != key) {
	    /* Direction changed without passing through a neutral report. */
	    if (axis_held[evt->caxis.axis] != KEY_DUMMY)
		Key_release(axis_held[evt->caxis.axis]);
	    Key_press(key);
	    axis_held[evt->caxis.axis] = key;
	}
	return true;

    default:
	return false;
    }
}

#endif /* GAMEPAD_MAPPING_TEST */
