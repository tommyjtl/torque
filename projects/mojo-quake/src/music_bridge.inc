/* Optional local CD tracks. PCM WAV data stays on disk and is read on the game
 * thread. SDL converts at most a small block at a time. The audio callback
 * consumes converted samples under SDL's existing audio-device lock. */
#include "SDL.h"
#include "common.h"
#include "console.h"
#include "sound.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static FILE *music_file;
static SDL_AudioStream *music_stream;
static uint32_t music_bytes;
static byte music_track, music_volume = 255;
static int music_paused;
static SDL_AudioFormat music_format;

static int track_path(char *path, size_t size, int number)
{
    int n = snprintf(path, size, "%s/id1/music/track%02d.wav", com_basedir, number);
    return number >= 2 && number <= 99 && n > 0 && (size_t)n < size;
}

int CDDrv_IsAudioTrack(byte track)
{
    char path[MAX_OSPATH];
    return track_path(path, sizeof path, track) && !access(path, R_OK);
}

static uint16_t le16(const byte *bytes) { return bytes[0] | ((uint16_t)bytes[1] << 8); }

static uint32_t le32(const byte *bytes) { return le16(bytes) | ((uint32_t)le16(bytes + 2) << 16); }

void CDDrv_Stop(void)
{
    SDL_LockAudio();
    if (music_stream)
        SDL_FreeAudioStream(music_stream);
    music_stream = NULL;
    music_track = 0;
    SDL_UnlockAudio();
    if (music_file)
        fclose(music_file);
    music_file = NULL;
    music_bytes = 0;
}

void mq_update_music(void)
{
    byte buffer[16384];
    if (!music_file || music_paused)
        return;
    for (;;) {
        SDL_LockAudio();
        int queued = SDL_AudioStreamAvailable(music_stream);
        SDL_UnlockAudio();
        if (queued >= shm->speed * shm->channels * (shm->samplebits / 8) / 3)
            return;
        size_t want = music_bytes < sizeof buffer ? music_bytes : sizeof buffer;
        size_t count = fread(buffer, 1, want, music_file);
        music_bytes -= count;
        SDL_LockAudio();
        int failed = count && SDL_AudioStreamPut(music_stream, buffer, count) < 0;
        if (!music_bytes || count != want || failed) {
            SDL_AudioStreamFlush(music_stream);
            SDL_UnlockAudio();
            fclose(music_file);
            music_file = NULL;
            return;
        }
        SDL_UnlockAudio();
    }
}

void mq_mix_music(byte *out, int count)
{
    byte samples[4096];
    if (!music_stream || music_paused)
        return;
    while (count > 0) {
        int bytes = SDL_AudioStreamGet(music_stream, samples,
                                       count < (int)sizeof samples ? count : (int)sizeof samples);
        if (bytes <= 0)
            break;
        SDL_MixAudioFormat(out, samples, music_format, bytes, music_volume * SDL_MIX_MAXVOLUME / 255);
        out += bytes;
        count -= bytes;
    }
}

int CDDrv_PlayTrack(byte track)
{
    char path[MAX_OSPATH];
    byte head[16], chunk[8];
    if (!shm || !track_path(path, sizeof path, track))
        return 1;
    CDDrv_Stop();
    FILE *f = fopen(path, "rb");
    if (!f)
        return 1;
    if (fread(head, 1, 12, f) != 12 || memcmp(head, "RIFF", 4) || memcmp(head + 8, "WAVE", 4))
        goto invalid;
    int channels = 0, rate = 0, bits = 0;
    while (fread(chunk, 1, 8, f) == 8) {
        uint32_t size = le32(chunk + 4);
        if (!memcmp(chunk, "fmt ", 4)) {
            if (size < 16 || fread(head, 1, 16, f) != 16 || le16(head) != 1)
                goto invalid;
            channels = le16(head + 2);
            rate = le32(head + 4);
            bits = le16(head + 14);
            if ((channels != 1 && channels != 2) || rate < 8000 || rate > 192000 ||
                (bits != 8 && bits != 16))
                goto invalid;
            size -= 16;
        } else if (!memcmp(chunk, "data", 4)) {
            if (!channels || !size || size % (channels * (bits / 8)))
                goto invalid;
            music_format = shm->samplebits == 8 ? AUDIO_U8 : AUDIO_S16SYS;
            SDL_AudioStream *converted =
                SDL_NewAudioStream(bits == 8 ? AUDIO_U8 : AUDIO_S16LSB, channels, rate, music_format,
                                   shm->channels, shm->speed);
            if (!converted)
                goto invalid;
            music_file = f;
            music_bytes = size;
            SDL_LockAudio();
            music_stream = converted;
            music_track = track;
            music_paused = 0;
            SDL_UnlockAudio();
            mq_update_music();
            Con_DPrintf("Playing local track %02d\n", track);
            return 0;
        }
        if (fseek(f, (long)size + (size & 1), SEEK_CUR))
            goto invalid;
    }
invalid:
    fclose(f);
    Con_Printf("Could not play PCM WAV track %02d\n", track);
    return 1;
}

int CDDrv_IsPlaying(byte track)
{
    SDL_LockAudio();
    int playing = track == music_track &&
                  (music_file || (music_stream && SDL_AudioStreamAvailable(music_stream) > 0));
    SDL_UnlockAudio();
    return playing;
}
int CDDrv_InitDevice(void) { return shm ? 0 : -1; }
void CDDrv_CloseDevice(void) { CDDrv_Stop(); }
void CDDrv_Eject(void) { CDDrv_Stop(); }
void CDDrv_CloseDoor(void) {}
void CDDrv_Pause(void)
{
    SDL_LockAudio();
    music_paused = 1;
    SDL_UnlockAudio();
}
void CDDrv_Resume(byte track)
{
    SDL_LockAudio();
    music_paused = 0;
    SDL_UnlockAudio();
}
int CDDrv_GetMaxTrack(byte *track)
{
    *track = 99;
    return 0;
}
int CDDrv_SetVolume(byte volume)
{
    SDL_LockAudio();
    music_volume = volume;
    SDL_UnlockAudio();
    return volume;
}
