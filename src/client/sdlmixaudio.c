/*
 * XPilot NG, a multiplayer space war game.
 *
 * Audio device backend built on SDL2_mixer.
 *
 * This replaces the OpenAL/freealut backend. It implements exactly the same
 * six audioDevice* entry points declared in caudio.h, so the event mapping in
 * caudio.c — which reads sounds.txt and decides which sample a game event
 * plays — is untouched.
 *
 * Two details of the original design are load-bearing and are preserved here.
 *
 * First, a sounds.txt entry may carry parameters: "thrust.wav,0.05,1" means
 * the sample thrust.wav, at gain 0.05, looping. Only the part before the
 * first comma is a filename.
 *
 * Second, looping sounds are stopped by *absence*. The protocol has no "stop"
 * event; while a ship thrusts the server keeps re-sending the thrust event,
 * and the backend is expected to stop a loop once the events stop arriving.
 * That is what audioDeviceUpdate does, and why it is not a no-op — without it
 * the thrust sound would loop forever after a single burst.
 *
 * On positional audio: the protocol carries only a sound index and a volume
 * (see Receive_audio in netclient.c and queue_audio in the server), so the
 * client is never told where a sound came from. Stereo panning is therefore
 * not implementable without extending the protocol and breaking compatibility
 * with existing servers. The server's distance-derived volume is what conveys
 * position, and it is honoured here.
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

#include "xpclient.h"
#include "caudio.h"

#include <SDL.h>
#include <SDL_mixer.h>

/*
 * How many sounds may overlap. XPilot can fire off a lot at once in a
 * firefight; beyond this SDL_mixer refuses the newest, which is preferable to
 * cutting short one already playing.
 */
#define AUDIO_CHANNELS 32

typedef struct {
    Mix_Chunk *chunk;
    float      gain;		/* per-sample multiplier from sounds.txt */
    int        loop;
} sample_t;

/* One entry per currently looping sample. */
static struct {
    sample_t *sample;
    int       channel;
    long      last_seen;	/* frame on which the event last arrived */
} active_loops[AUDIO_CHANNELS];

static long frame_counter = 0;
static bool audio_open = false;

/*
 * Split "file.wav,gain,loop" into its parts. The caller's string is not
 * modified: caudio.c caches these filenames and reuses them, so chopping the
 * original in place would lose the parameters for every later lookup.
 */
static void sample_parse_info(const char *spec, char *name, size_t name_size,
			      float *gain, int *loop)
{
    const char *comma = strchr(spec, ',');
    size_t len;

    *gain = 1.0f;
    *loop = 0;

    len = (comma != NULL) ? (size_t)(comma - spec) : strlen(spec);
    if (len >= name_size)
	len = name_size - 1;
    memcpy(name, spec, len);
    name[len] = '\0';

    if (comma == NULL)
	return;

    *gain = (float)atof(comma + 1);

    comma = strchr(comma + 1, ',');
    if (comma != NULL)
	*loop = atoi(comma + 1);
}

int audioDeviceInit(char *display)
{
    UNUSED_PARAM(display);

    if (SDL_InitSubSystem(SDL_INIT_AUDIO) != 0) {
	warn("Could not initialise audio: %s", SDL_GetError());
	return -1;
    }

    /*
     * A small buffer keeps the gap between firing a shot and hearing it
     * short; 512 frames at 22050Hz is about 23ms. Too small and the mixer
     * underruns.
     */
    if (Mix_OpenAudio(22050, MIX_DEFAULT_FORMAT, 2, 512) != 0) {
	warn("Could not open audio device: %s", Mix_GetError());
	SDL_QuitSubSystem(SDL_INIT_AUDIO);
	return -1;
    }

    Mix_AllocateChannels(AUDIO_CHANNELS);
    memset(active_loops, 0, sizeof(active_loops));
    audio_open = true;

    xpinfo("Audio: SDL2_mixer, %d channels.", AUDIO_CHANNELS);
    return 0;
}

/* Volume is the server's 0..100; combine with the sample's own gain. */
static int mix_volume(const sample_t *s, int volume)
{
    float v;

    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;

    v = (float)volume / 100.0f * s->gain;
    if (v < 0.0f) v = 0.0f;
    if (v > 1.0f) v = 1.0f;

    return (int)(v * MIX_MAX_VOLUME);
}

void audioDevicePlay(char *filename, int type, int volume, void **priv)
{
    sample_t *sample;
    int i, free_slot = -1, channel;

    if (!audio_open || filename == NULL)
	return;

    sample = (sample_t *)*priv;
    if (sample == NULL) {
	static bool complained[MAX_SOUNDS];
	char name[PATH_MAX];
	float gain;
	int loop;

	sample_parse_info(filename, name, sizeof(name), &gain, &loop);

	sample = (sample_t *)malloc(sizeof(*sample));
	if (sample == NULL)
	    return;

	sample->chunk = Mix_LoadWAV(name);
	if (sample->chunk == NULL) {
	    /* Warn once per event type, not once per shot fired. */
	    if (type >= 0 && type < MAX_SOUNDS && !complained[type]) {
		complained[type] = true;
		warn("Could not load sound %s: %s", name, Mix_GetError());
	    }
	    free(sample);
	    return;
	}
	sample->gain = gain;
	sample->loop = loop;
	*priv = sample;
    }

    if (sample->loop) {
	/*
	 * Already looping? Then this is the server saying "still happening":
	 * refresh the volume and the timestamp, and do not start a second
	 * copy.
	 */
	for (i = 0; i < AUDIO_CHANNELS; i++) {
	    if (active_loops[i].sample == sample) {
		Mix_Volume(active_loops[i].channel, mix_volume(sample, volume));
		active_loops[i].last_seen = frame_counter;
		return;
	    }
	    if (active_loops[i].sample == NULL && free_slot < 0)
		free_slot = i;
	}

	if (free_slot < 0)
	    return;		/* no room to track another loop */

	channel = Mix_PlayChannel(-1, sample->chunk, -1);	/* -1 = forever */
	if (channel < 0)
	    return;

	Mix_Volume(channel, mix_volume(sample, volume));
	active_loops[free_slot].sample = sample;
	active_loops[free_slot].channel = channel;
	active_loops[free_slot].last_seen = frame_counter;
	return;
    }

    channel = Mix_PlayChannel(-1, sample->chunk, 0);
    if (channel < 0)
	return;			/* all channels busy; dropping this is fine */

    Mix_Volume(channel, mix_volume(sample, volume));
}

void audioDeviceEvents(void)
{
}

/*
 * Stop looping sounds whose event stopped arriving. Called once per frame.
 * A loop is kept while its event was seen this frame or the previous one; the
 * one frame of slack absorbs a single dropped or late packet without the
 * sound stuttering.
 */
void audioDeviceUpdate(void)
{
    int i;

    if (!audio_open)
	return;

    frame_counter++;

    for (i = 0; i < AUDIO_CHANNELS; i++) {
	if (active_loops[i].sample == NULL)
	    continue;
	if (active_loops[i].last_seen >= frame_counter - 1)
	    continue;

	Mix_HaltChannel(active_loops[i].channel);
	active_loops[i].sample = NULL;
    }
}

void audioDeviceFree(void *priv)
{
    sample_t *sample = (sample_t *)priv;
    int i;

    if (sample == NULL)
	return;

    /* Never leave a halted channel pointing at a freed chunk. */
    for (i = 0; i < AUDIO_CHANNELS; i++) {
	if (active_loops[i].sample == sample) {
	    Mix_HaltChannel(active_loops[i].channel);
	    active_loops[i].sample = NULL;
	}
    }

    if (sample->chunk != NULL)
	Mix_FreeChunk(sample->chunk);
    free(sample);
}

void audioDeviceClose(void)
{
    if (!audio_open)
	return;

    Mix_HaltChannel(-1);
    memset(active_loops, 0, sizeof(active_loops));
    Mix_CloseAudio();
    SDL_QuitSubSystem(SDL_INIT_AUDIO);
    audio_open = false;
}
