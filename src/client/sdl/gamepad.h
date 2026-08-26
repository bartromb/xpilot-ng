/*
 * XPilot NG, a multiplayer space war game.
 *
 * Gamepad support via the SDL2 GameController API.
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation; either version 2 of the License, or (at your option)
 * any later version.  See the COPYING file for details.
 */

#ifndef GAMEPAD_H
#define GAMEPAD_H

/*
 * Axis dead zone, as a fraction of the Sint16 range SDL reports. Roughly 25%,
 * which is forgiving enough for a worn stick without feeling unresponsive.
 */
#define GAMEPAD_DEADZONE 8000

void   Gamepad_init(void);
void   Gamepad_cleanup(void);
bool   Gamepad_process(SDL_Event *evt);

/* Pure mapping functions, exposed for testing without a controller. */
keys_t Gamepad_button_action(int button);
keys_t Gamepad_axis_action(int axis, int value, bool *held);

#endif /* GAMEPAD_H */
