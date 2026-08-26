/*
 * XPilot NG, a multiplayer space war game.
 *
 * Phase 4b visual effects: state, options and shared drawing helpers.
 *
 * Everything here is presentation only. The rules for this phase are that no
 * effect may change where an object appears to be, how large it appears for
 * the purpose of judging a collision, or when anything happens; that every
 * effect is individually switchable at runtime; and that a single "classic"
 * switch turns all of them off and restores the plain vector look.
 *
 * The glow helpers below satisfy the first rule by construction: they redraw
 * the *same* geometry with a wider line, so the centre line stays exactly
 * where it was and only the surrounding pixels change.
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
#include "sdlpaint.h"
#include "effects.h"

bool classicRender;
bool glowEffect;
double glowWidth;
int glowLayers;

bool Effects_classic(void)
{
    return classicRender;
}

bool Effects_glow(void)
{
    return !classicRender && glowEffect;
}

/*
 * Draw a display list several times, each pass wider and fainter than the
 * last, using additive blending so overlapping passes brighten rather than
 * replace. The caller then draws its normal, crisp pass on top.
 *
 * Passes go widest first so the faint outer halo is laid down before the
 * brighter inner ones.
 */
void Glow_draw(glow_emit_fn emit, void *data, unsigned int rgb,
	       double base_width)
{
    int layer;
    GLboolean blend_was_on;
    GLint src, dst;

    if (!Effects_glow())
	return;

    blend_was_on = glIsEnabled(GL_BLEND);
    glGetIntegerv(GL_BLEND_SRC, &src);
    glGetIntegerv(GL_BLEND_DST, &dst);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);

    for (layer = glowLayers; layer >= 1; layer--) {
	double width = base_width * (1.0 + layer * glowWidth);
	int alpha = (int)(GLOW_BASE_ALPHA / (double)(layer * layer));

	if (width < 1.0)
	    width = 1.0;
	if (alpha < 1)
	    continue;
	if (alpha > 255)
	    alpha = 255;

	set_alphacolor((rgb << 8) | (unsigned)alpha);
	glLineWidth((GLfloat)width);
	emit(data);
    }

    glLineWidth(1);
    glBlendFunc(src, dst);
    if (!blend_was_on)
	glDisable(GL_BLEND);
}

static void Emit_call_list(void *data)
{
    glCallList(*(unsigned int *)data);
}

void Glow_call_list(unsigned int list, unsigned int rgb, double base_width)
{
    Glow_draw(Emit_call_list, &list, rgb, base_width);
}


/* ------------------------------------------------------------------ *
 * Parallax starfield
 *
 * Purely decorative: drawn behind everything, never interacts with the
 * simulation, and reads only the view position the renderer already has.
 *
 * Stars are generated once from a fixed seed, so the same sky appears every
 * frame and every session rather than shimmering. Each layer scrolls at a
 * fraction of the view movement, which is what produces the depth cue: the
 * far layer barely moves, the near layer nearly keeps up with the world.
 * ------------------------------------------------------------------ */

bool starfieldEffect;
int starfieldDensity;

#define STARFIELD_LAYERS 3
#define STARFIELD_TILE   1024	/* stars repeat on this grid, in pixels */
#define STARFIELD_MAX    (STARFIELD_TILE * STARFIELD_TILE / 4096)

typedef struct {
    short x, y;
    unsigned char brightness;
} star_t;

static star_t stars[STARFIELD_LAYERS][STARFIELD_MAX];
static int    star_count[STARFIELD_LAYERS];
static bool   stars_ready = false;

/* Scroll fraction and relative brightness per layer, far to near. */
static const double star_parallax[STARFIELD_LAYERS]   = { 0.15, 0.35, 0.60 };
static const double star_brightness[STARFIELD_LAYERS] = { 0.40, 0.65, 1.00 };

/*
 * A small deterministic generator. Not using rand() on purpose: the sky must
 * not depend on, or perturb, whatever else has drawn from the global stream.
 */
static unsigned int star_rand(unsigned int *state)
{
    *state = (*state * 1103515245u) + 12345u;
    return (*state >> 16) & 0x7fff;
}

static void Starfield_generate(void)
{
    unsigned int state = 0x5eed1234u;
    int layer, i, n;

    for (layer = 0; layer < STARFIELD_LAYERS; layer++) {
	n = (STARFIELD_MAX * starfieldDensity) / 100;
	if (n > STARFIELD_MAX) n = STARFIELD_MAX;
	if (n < 0) n = 0;
	star_count[layer] = n;

	for (i = 0; i < n; i++) {
	    stars[layer][i].x = (short)(star_rand(&state) % STARFIELD_TILE);
	    stars[layer][i].y = (short)(star_rand(&state) % STARFIELD_TILE);
	    /* Vary brightness so a layer does not look like a flat grid. */
	    stars[layer][i].brightness =
		(unsigned char)(120 + (star_rand(&state) % 136));
	}
    }
    stars_ready = true;
}

bool Effects_starfield(void)
{
    return !classicRender && starfieldEffect;
}

/*
 * view_x/view_y are the world coordinates of the bottom-left of the view;
 * w/h are the drawable size.
 */
void Starfield_paint(double view_x, double view_y, int w, int h)
{
    int layer, i, tx, ty;
    GLboolean blend_was_on;
    GLint src, dst;

    if (!Effects_starfield())
	return;

    if (!stars_ready)
	Starfield_generate();

    blend_was_on = glIsEnabled(GL_BLEND);
    glGetIntegerv(GL_BLEND_SRC, &src);
    glGetIntegerv(GL_BLEND_DST, &dst);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);

    glPointSize(1.0f);

    for (layer = 0; layer < STARFIELD_LAYERS; layer++) {
	/* Offset this layer by its share of the view movement, wrapped into
	 * one tile so the pattern repeats seamlessly across the screen. */
	double ox = view_x * star_parallax[layer];
	double oy = view_y * star_parallax[layer];
	int shift_x = (int)ox % STARFIELD_TILE;
	int shift_y = (int)oy % STARFIELD_TILE;

	if (shift_x < 0) shift_x += STARFIELD_TILE;
	if (shift_y < 0) shift_y += STARFIELD_TILE;

	glBegin(GL_POINTS);
	for (i = 0; i < star_count[layer]; i++) {
	    int bx = stars[layer][i].x - shift_x;
	    int by = stars[layer][i].y - shift_y;
	    int a = (int)(stars[layer][i].brightness * star_brightness[layer]);

	    if (bx < 0) bx += STARFIELD_TILE;
	    if (by < 0) by += STARFIELD_TILE;

	    glColor4ub(0xff, 0xff, 0xff, (GLubyte)a);

	    /* Repeat the tile to cover the whole view. */
	    for (ty = by; ty < h; ty += STARFIELD_TILE)
		for (tx = bx; tx < w; tx += STARFIELD_TILE)
		    glVertex2i(tx, ty);
	}
	glEnd();
    }

    glBlendFunc(src, dst);
    if (!blend_was_on)
	glDisable(GL_BLEND);
}

void Store_effects_options(void)
{
    static xp_option_t options[] = {

	XP_BOOL_OPTION(
	    "classicRender",
	    false,
	    &classicRender,
	    NULL,
	    XP_OPTFLAG_DEFAULT,
	    "Turn off every added visual effect and draw the plain vector\n"
	    "look the client had before they existed. Overrides the\n"
	    "individual effect options.\n"),

	XP_BOOL_OPTION(
	    "glowEffect",
	    true,
	    &glowEffect,
	    NULL,
	    XP_OPTFLAG_DEFAULT,
	    "Draw a soft additive glow around walls, ships and shots.\n"
	    "Has no effect when classicRender is on.\n"),

	XP_DOUBLE_OPTION(
	    "glowWidth",
	    1.5, 0.1, 4.0,
	    &glowWidth,
	    NULL,
	    XP_OPTFLAG_DEFAULT,
	    "How far the glow spreads, as a multiple of the line width\n"
	    "per layer.\n"),

	XP_BOOL_OPTION(
	    "starfieldEffect",
	    true,
	    &starfieldEffect,
	    NULL,
	    XP_OPTFLAG_DEFAULT,
	    "Draw a parallax starfield behind the map. Purely decorative;\n"
	    "has no effect when classicRender is on.\n"),

	XP_INT_OPTION(
	    "starfieldDensity",
	    45, 0, 100,
	    &starfieldDensity,
	    NULL,
	    XP_OPTFLAG_DEFAULT,
	    "How many stars to draw, as a percentage of the maximum.\n"),

	XP_INT_OPTION(
	    "glowLayers",
	    3, 1, 4,
	    &glowLayers,
	    NULL,
	    XP_OPTFLAG_DEFAULT,
	    "How many glow layers to draw. More is smoother and costs\n"
	    "more fill rate.\n"),
    };
    int i;

    for (i = 0; i < (int)(sizeof(options) / sizeof(options[0])); i++)
	Store_option(&options[i]);
}
