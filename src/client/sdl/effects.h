/*
 * XPilot NG, a multiplayer space war game.
 *
 * Phase 4b visual effects.
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the Free
 * Software Foundation; either version 2 of the License, or (at your option)
 * any later version.  See the COPYING file for details.
 */

#ifndef EFFECTS_H
#define EFFECTS_H

/*
 * Alpha of the innermost glow layer. Outer layers fall off as 1/layer^2, so
 * the halo fades quickly rather than turning into a fog.
 */
#define GLOW_BASE_ALPHA 110

extern bool   classicRender;
extern bool   glowEffect;
extern double glowWidth;
extern int    glowLayers;

bool Effects_classic(void);
bool Effects_glow(void);

void Glow_call_list(unsigned int list, unsigned int rgb, double base_width);

void Store_effects_options(void);

#endif /* EFFECTS_H */
