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

/*
 * Emit the geometry to be glowed. Called once per glow layer; the callback
 * must not change colour or line width, which the glow controls.
 */
typedef void (*glow_emit_fn)(void *data);

void Glow_draw(glow_emit_fn emit, void *data, unsigned int rgb,
	       double base_width);
void Glow_call_list(unsigned int list, unsigned int rgb, double base_width);

extern bool starfieldEffect;
extern int  starfieldDensity;

bool Effects_starfield(void);
void Starfield_paint(double view_x, double view_y, int w, int h);

extern bool particleEffect;
extern int  particleLife;

bool Effects_particles(void);
void Particles_spawn(double x, double y, int r, int g, int b);
void Particles_update(void);
void Particles_paint(void);

void Store_effects_options(void);

#endif /* EFFECTS_H */
