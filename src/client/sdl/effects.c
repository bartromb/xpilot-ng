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
void Glow_call_list(unsigned int list, unsigned int rgb, double base_width)
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
	glCallList(list);
    }

    glLineWidth(1);
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
