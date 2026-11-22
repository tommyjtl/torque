// Linux/SDL adapter for the Mojo sampler. No web engine or audio work on the UI thread.
#include <SDL.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/file.h>
#include <unistd.h>
#include "build/skin.h"
#include "inspection.h"

enum { RATE = 48000, TAKE = RATE * 8, VOICES = 24, BLOCK = 256 };
enum {
    SLOT,
    NOTE,
    BPM,
    RUN,
    PAT,
    HEAD,
    FX,
    NEXT_VOICE,
    LIGHTS,
    PEAK,
    PREV_FX,
    DELAY_CURSOR,
    DELAY_VALID
};
enum { SOUND = 16, PATTERN, TEMPO, DIAL_A, DIAL_B, RECORD, EFFECT, PLAY, WRITE, RESET, EXIT };
extern void bap_strike(int32_t *, int32_t *, int32_t *, const int *, const int *, int *, int *, float *,
                       int32_t, int32_t, int32_t);
extern void bap_render(int32_t *, int32_t *, int32_t *, const int *, const int *, int *, int *, int *,
                       float *, float *, float *, float *, float *, float *, int32_t);

static int s[13], info[VOICES * 6], lengths[16], pitches[256], levels[16], steps[4096];
static float voices[VOICES * 3], dsp[5], takes[16 * TAKE], staging[TAKE], delay_line[RATE], *factory;
static SDL_AudioDeviceID output, input;
static SDL_Renderer *renderer;
static SDL_Window *window;
static unsigned live_lamps;
static SDL_Texture *face, *comic[8], *font;
static int mode = -1, writing, dial, fx_keys, quit, pose, destination = -1, recorded, limit,
           finish_take, cancel_take;
static int down[SDL_NUM_SCANCODES + 4], held_pads[16], fx_order[16], fx_serial;
static unsigned notice_until, last_turn, record_since;
static int notice_bars = -1;
static int last_direction, encoder_angle[2];
static char notice[56], audio_error[40];
static const char *const sounds[] = {"Glass keys", "Sub bass", "Bell tone",  "Wire pluck",
                                     "Soft tine",  "Reed",     "Overtone",   "Pulse",
                                     "Break kit",  "Dust kit", "Metal kit",  "Click kit",
                                     "Block kit",  "Tape kit", "Bright kit", "Chip kit"};
static const char *const effects[] = {
    "LOW PASS", "HIGH PASS", "TELEPHONE", "AUTO WAH", "DRIVE",   "FUZZ", "CRUSH",    "WAVEFOLD",
    "SLAPBACK", "DUB ECHO",  "FLANGER",   "CHORUS",   "TREMOLO", "CHOP", "RING MOD", "AUTO PAN"};
static const char *const drums[] = {"KICK", "SNARE", "HAT", "CLAP", "TOM", "RIM", "BELL", "RIDE"};
static const int initial[16] = {0, -1, 2, -1, 1, -1, 2, 2, 0, -1, 2, 0, 1, -1, 2, 3};
static int clamp(int n, int lo, int hi) { return n < lo ? lo : n > hi ? hi : n; }
static void say(const char *text) {
    snprintf(notice, sizeof notice, "%s", text);
    notice_until = SDL_GetTicks() + 1200;
    notice_bars = -1;
}
static void audio_block(void *unused, Uint8 *bytes, int size) {
    (void)unused;
    bap_render(s, info, lengths, wave_offsets, wave_lengths, pitches, levels, steps, voices, dsp,
               factory, takes, delay_line, (float *)bytes, size / (2 * sizeof(float)));
}
static void note(int pad) {
    bap_strike(s, info, lengths, wave_offsets, wave_lengths, pitches, levels, voices, s[SLOT], pad, 0);
}
static void clear_holds(void) {
    memset(down, 0, sizeof down);
    memset(held_pads, 0, sizeof held_pads);
    memset(fx_order, 0, sizeof fx_order);
    fx_keys = fx_serial = 0;
    s[FX] = -1;
}
static void silence(void) {
    memset(info, 0, sizeof info);
    memset(dsp, 0, sizeof dsp);
    s[RUN] = 0;
    s[HEAD] = -1;
    s[LIGHTS] = s[PEAK] = 0;
    s[PREV_FX] = -1;
    s[DELAY_VALID] = 0;
    clear_holds();
}
static void reset(void) {
    silence();
    memset(lengths, 0, sizeof lengths);
    memset(pitches, 0, sizeof pitches);
    for (int i = 0; i < 4096; i++)
        steps[i] = -1;
    for (int i = 0; i < 16; i++) {
        levels[i] = 50;
        steps[8 * 16 + i] = initial[i];
    }
    s[SLOT] = 8;
    s[NOTE] = 0;
    s[BPM] = 96;
    s[PAT] = 0;
    writing = dial = pose = last_direction = 0;
    encoder_angle[0] = encoder_angle[1] = 0;
    mode = -1;
    cancel_take = 1;
    say("READY");
}
static int free_frames(int slot) {
    int n = RATE * 40;
    for (int i = 0; i < 16; i++)
        if (i != slot)
            n -= lengths[i];
    return clamp(n, 0, TAKE);
}
static void transport(void) {
    if (s[RUN]) {
        silence();
        say("STOP");
    } else {
        s[RUN] = 1;
        s[HEAD] = -1;
        dsp[0] = 0;
        say("PLAYING");
    }
}
static void choose_pad(int pad) {
    ++pose;
    if (destination >= 0)
        return;
    if (fx_keys) {
        if (s[RUN]) {
            fx_order[pad] = ++fx_serial;
            s[FX] = pad;
            notice_until = 0;
        }
        return;
    }
    if (mode == RECORD) {
        mode = -1;
        limit = free_frames(pad);
        if (limit < RATE / 20) {
            say("MEMORY FULL");
            return;
        }
        destination = pad;
        recorded = finish_take = cancel_take = 0;
        return;
    }
    if (mode == PATTERN) {
        s[PAT] = pad;
        mode = -1;
        notice_until = 0;
        return;
    }
    if (mode == SOUND) {
        s[SLOT] = pad;
        s[NOTE] = 0;
        mode = -1;
        if (!s[RUN])
            note(0);
        notice_until = 0;
        return;
    }
    if (writing) {
        int *step = &steps[(s[PAT] * 16 + s[SLOT]) * 16 + pad];
        *step = (*step >= 0) ? -1 : s[NOTE];
        if (*step >= 0 && !s[RUN])
            note(*step);
        return;
    }
    s[NOTE] = pad;
    note(pad);
    char text[32];
    if (lengths[s[SLOT]])
        snprintf(text, sizeof text, "SLICE %02d", pad + 1);
    else if (s[SLOT] >= 8)
        snprintf(text, sizeof text, "%s%s", drums[pad % 8], pad >= 8 ? " II" : "");
    else
        snprintf(text, sizeof text, "NOTE %02d", pad + 1);
    say(text);
}
static void turn(int direction, int accelerated) {
    unsigned now = SDL_GetTicks(), dt = now - last_turn;
    int factor = accelerated && direction == last_direction ? (dt <= 45 ? 4 : dt <= 100 ? 2 : 1) : 1;
    last_direction = direction;
    last_turn = now;
    int delta = direction * factor;
    encoder_angle[dial] = direction ? (encoder_angle[dial] + 15 * direction) % 360 : 0;
    char text[40];
    int bars;
    if (!dial && mode == TEMPO) {
        s[BPM] = direction ? clamp(s[BPM] + delta, 60, 240) : 96;
        bars = lroundf((s[BPM] - 60) * 48.f / 180);
        snprintf(text, sizeof text, "%d BPM", s[BPM]);
    } else if (!dial) {
        int index = s[SLOT] * 16 + s[NOTE], old = pitches[index];
        pitches[index] = direction ? clamp(old + delta, -12, 12) : 0;
        float ratio = exp2f((pitches[index] - old) / 12.0f);
        for (int v = 0; v < VOICES; v++)
            if (info[6 * v] == s[SLOT] + 1 && info[6 * v + 1] == s[NOTE])
                voices[3 * v + 1] *= ratio;
        bars = (pitches[index] + 12) * 2;
        snprintf(text, sizeof text, "PAD %02d %d ST", s[NOTE] + 1, pitches[index]);
    } else {
        int *level = &levels[s[SLOT]];
        *level = direction ? clamp(*level + delta * 5, 0, 100) : 50;
        bars = lroundf(*level * 48.f / 100);
        snprintf(text, sizeof text, "VOLUME %d%%", *level);
    }
    say(text);
    notice_bars = bars;
}
static void press(int control, int handle) {
    if (control < 0 || down[handle])
        return;
    down[handle] = control + 1;
    last_direction = 0;
    if (control == EXIT) {
        quit = 1;
        return;
    }
    if (control == RESET) {
        reset();
        return;
    }
    if (destination >= 0) {
        if (control == RECORD)
            finish_take = 1;
        return;
    }
    if (control < 16) {
        held_pads[control]++;
        choose_pad(control);
        return;
    }
    notice_until = 0;
    switch (control) {
    case PLAY:
        transport();
        break;
    case WRITE:
        mode = -1;
        writing = !writing;
        break;
    case EFFECT:
        fx_keys++;
        break;
    case DIAL_A:
    case DIAL_B:
        dial = control == DIAL_B;
        break;
    default:
        mode = mode == control ? -1 : control;
        if (mode == TEMPO)
            dial = 0;
        break;
    }
}
static void release(int handle) {
    int control = down[handle] - 1;
    down[handle] = 0;
    if (control < 0)
        return;
    if (control == EFFECT && fx_keys > 0 && --fx_keys == 0) {
        memset(fx_order, 0, sizeof fx_order);
        s[FX] = -1;
    }
    if (control < 16 && held_pads[control] > 0 && --held_pads[control] == 0) {
        fx_order[control] = 0;
        int rank = 0;
        s[FX] = -1;
        for (int i = 0; i < 16; i++)
            if (fx_order[i] > rank) {
                rank = fx_order[i];
                s[FX] = i;
            }
    }
}
static const char *device_name(int capture) {
    const char *want = capture ? "Headset microphone" : "Lineout playback";
    for (int i = 0; i < SDL_GetNumAudioDevices(capture); i++) {
        const char *name = SDL_GetAudioDeviceName(i, capture);
        if (name && strstr(name, want))
            return name;
    }
    return NULL;
}
static SDL_AudioDeviceID open_audio(int capture) {
    const char *name = device_name(capture);
    if (!name) {
        fprintf(stderr, "Missing %s device\n", capture ? "headset microphone" : "Line Out");
        return 0;
    }
    SDL_AudioSpec spec = {0}, got = {0};
    spec.freq = RATE;
    spec.format = AUDIO_F32SYS;
    spec.channels = capture ? 1 : 2;
    spec.samples = BLOCK;
    spec.callback = capture ? NULL : audio_block;
    SDL_AudioDeviceID dev = SDL_OpenAudioDevice(name, capture, &spec, &got, 0);
    if (dev)
        fprintf(stderr, "%s: %s, %d Hz, %d frames (%s)\n", capture ? "input" : "output", name, got.freq,
                got.samples, SDL_GetCurrentAudioDriver());
    else
        fprintf(stderr, "Audio open failed: %s\n", SDL_GetError());
    return dev;
}
// Capture is queued by SDL off the render thread. Swap the take only after success.
static void capture_pump(void) {
    if (destination < 0)
        return;
    if (!input && !cancel_take && !finish_take) {
        input = open_audio(1);
        if (!input) {
            destination = -1;
            say("MIC UNAVAILABLE");
            return;
        }
        record_since = SDL_GetTicks();
        SDL_PauseAudioDevice(input, 0);
    }
    if (input && !cancel_take && recorded < limit) {
        recorded +=
            (int)(SDL_DequeueAudio(input, staging + recorded, (limit - recorded) * sizeof(float)) /
                  sizeof(float));
    }
    unsigned elapsed = SDL_GetTicks() - record_since;
    if (!finish_take && !cancel_take && recorded < limit &&
        elapsed < (unsigned)(limit * 1000LL / RATE + 350))
        return;
    if (input) {
        SDL_CloseAudioDevice(input);
        input = 0;
    }
    if (!cancel_take && recorded >= RATE / 20) {
        SDL_LockAudioDevice(output);
        for (int v = 0; v < VOICES; v++)
            if (info[6 * v] == destination + 1)
                info[6 * v] = 0;
        memcpy(takes + (size_t)destination * TAKE, staging, recorded * sizeof(float));
        lengths[destination] = recorded;
        s[SLOT] = destination;
        s[NOTE] = 0;
        SDL_UnlockAudioDevice(output);
        say("SAMPLE SAVED");
    } else if (!cancel_take)
        say("MIC NO DATA");
    destination = -1;
    recorded = finish_take = cancel_take = 0;
}
static void *read_file(const char *name, size_t *n) {
    FILE *f = fopen(name, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END)) {
        fclose(f);
        return NULL;
    }
    long size = ftell(f);
    rewind(f);
    if (size <= 0) {
        fclose(f);
        return NULL;
    }
    void *data = malloc((size_t)size);
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size) {
        free(data);
        data = NULL;
    }
    fclose(f);
    *n = (size_t)size;
    return data;
}
static SDL_Texture *bitmap(const char *path) {
    SDL_Surface *surface = SDL_LoadBMP(path);
    if (!surface)
        return NULL;
    SDL_Texture *t = SDL_CreateTextureFromSurface(renderer, surface);
    SDL_FreeSurface(surface);
    return t;
}
static int skin(void) {
    face = bitmap("face.bmp");
    if (!face)
        return 0;
    for (int i = 0; i < 8; i++) {
        char path[32];
        snprintf(path, sizeof path, "comic%d.bmp", i);
        comic[i] = bitmap(path);
        if (!comic[i])
            return 0;
    }
    size_t n;
    void *data = read_file("font.rgba", &n);
    if (!data || n != 3072 * 200 * 4) {
        free(data);
        return 0;
    }
    font = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGBA32, SDL_TEXTUREACCESS_STATIC, 3072, 200);
    if (!font || SDL_UpdateTexture(font, NULL, data, 3072 * 4)) {
        free(data);
        return 0;
    }
    free(data);
    SDL_SetTextureBlendMode(font, SDL_BLENDMODE_BLEND);
    return 1;
}
static void color(unsigned c) { SDL_SetRenderDrawColor(renderer, c >> 16, c >> 8, c, 255); }
static void fill(int x, int y, int w, int h, unsigned c) {
    SDL_Rect r = {x, y, w, h};
    color(c);
    SDL_RenderFillRect(renderer, &r);
}
static void text(SDL_Rect box, int row, const char *str, unsigned c, int center) {
    int width = 0;
    for (const char *p = str; *p; p++)
        width += advances[row][(unsigned char)*p - 32];
    float scale = width > box.w ? (float)box.w / width : 1;
    float x = box.x + (center ? (box.w - width * scale) / 2 : 0);
    SDL_SetTextureColorMod(font, c >> 16, c >> 8, c);
    for (const char *p = str; *p; p++) {
        int ch = (unsigned char)*p - 32;
        SDL_Rect src = {ch * 32, row * 40, 32, 40};
        SDL_FRect dst = {x, box.y + box.h / 2 - 20 * scale, 32 * scale, 40 * scale};
        SDL_RenderCopyF(renderer, font, &src, &dst);
        x += advances[row][ch] * scale;
    }
}
static void lamp(int i, int on) {
    if (on)
        live_lamps |= 1u << i;
    SDL_Rect plate = switches[i];
    int x = plate.x + plate.w / 2 - 4, y = plate.y - 5;
    fill(x, y, 8, 4, on ? 0xc57366 : 0x613837);
    fill(x + 2, y + 1, 4, 2, on ? 0xffe8ca : 0x6a4240);
}
static void knob(int i) {
    SDL_Rect r = switches[i];
    float angle = encoder_angle[i - DIAL_A] * 3.14159265f / 180;
    float ax = sinf(angle), ay = -cosf(angle);
    int x = r.x + r.w / 2, y = r.y + r.h / 2;
    for (int k = -2; k <= 3; k++) {
        color(k == -2 ? 0x686866 : k == 3 ? 0xe1e1de : 0x969692);
        float cx = x + k * ay, cy = y - k * ax;
        SDL_RenderDrawLine(renderer, lroundf(cx - 14 * ax), lroundf(cy - 14 * ay),
                           lroundf(cx + 14 * ax), lroundf(cy + 14 * ay));
    }
}
static int meter_bars(int peak_milli, unsigned now) {
    if (notice_bars >= 0 && notice_until && !SDL_TICKS_PASSED(now, notice_until) && destination < 0)
        return notice_bars;
    return peak_milli > 0 ? clamp((int)(48 + 20 * log10f(peak_milli / 1000.f)), 0, 48) : 0;
}
static void draw(void) {
    bool inspecting = inspect_open();
    if (inspecting && !inspect_prepare(window, renderer)) {
        inspecting = false;
        say("3D UNAVAILABLE");
    }
    live_lamps = 0;
    int v[13];
    SDL_LockAudioDevice(output);
    memcpy(v, s, sizeof v);
    SDL_UnlockAudioDevice(output);
    const int slot = v[SLOT], bank = v[PAT];
    int used = 0;
    for (int i = 0; i < 16; i++)
        used += lengths[i] > 0;
    char name[42], label[42], value[24];
    const char *status = "READY";
    SDL_RenderClear(renderer);
    SDL_RenderCopy(renderer, face, NULL, NULL);
    int frame = (pose + (v[RUN] ? ((v[HEAD] < 0 ? 0 : v[HEAD]) / (v[BPM] > 120 ? 4 : 2)) : 0)) % 8;
    SDL_RenderCopy(renderer, comic[frame], NULL, &fields[0]);
    snprintf(label, sizeof label, "%s / %02d",
             lengths[slot] ? "SLICE"
             : slot < 8    ? "MELO"
                           : "DRUM",
             slot + 1);
    snprintf(name, sizeof name, "%s", sounds[slot]);
    if (lengths[slot])
        snprintf(name, sizeof name, "Sample %02d", slot + 1);
    if (mode == RECORD) {
        snprintf(label, sizeof label, "%d/16 RECORDED", used);
        snprintf(name, sizeof name, "%s", used ? "Orange = take" : "All factory");
        status = "REC > SLOT";
    } else if (mode == SOUND)
        status = "SELECT SOUND";
    else if (mode == PATTERN)
        status = "SELECT PATTERN";
    else if (mode == TEMPO)
        status = "SET TEMPO";
    else if (writing)
        status = "WRITE";
    else if (v[RUN])
        status = "PLAYING";
    if (fx_keys)
        status = v[FX] >= 0 ? effects[v[FX]] : v[RUN] ? "FX: HOLD PAD" : "FX: PRESS PLAY";
    if (SDL_TICKS_PASSED(notice_until, SDL_GetTicks()) && notice_until)
        status = notice;
    if (audio_error[0])
        status = audio_error;
    if (destination >= 0) {
        int remain =
            input ? clamp(limit - (int)((SDL_GetTicks() - record_since) * 48), 0, limit) : limit;
        snprintf(name, sizeof name, "%ds left", (remain + RATE - 1) / RATE);
        snprintf(label, sizeof label, "REC / %02d", destination + 1);
        status = "RECORDING";
    }
    SDL_Rect bankbox = fields[1];
    bankbox.w = 115;
    text(bankbox, 0, label, 0x282829, 0);
    text(fields[2], 1, name, 0x282829, 0);
    SDL_Rect msg = fields[3];
    msg.x = fields[3].x + fields[3].w / 2 - 62;
    msg.w = 124;
    text(msg, 2, status, 0x282829, 1);
    snprintf(value, sizeof value, "%03d", v[BPM]);
    text(fields[4], 3, value, 0x282829, 0);
    snprintf(value, sizeof value, "%02d", bank + 1);
    text(fields[5], 4, value, 0x282829, 0);
    SDL_Rect meter = fields[6];
    int bars = meter_bars(v[PEAK], SDL_GetTicks());
    for (int i = 0; i < bars; i++)
        fill(meter.x + i * meter.w / 48, meter.y, 3, meter.h, 0x302f30);
    for (int i = 0; i < 16; i++) {
        int indicator =
            mode == RECORD || (mode == SOUND && slot == i) || (mode == PATTERN && bank == i);
        if (fx_keys)
            indicator = fx_order[i] > 0;
        else if (destination >= 0)
            indicator = i == destination && (SDL_GetTicks() - record_since) / 1000 % 2 == 0;
        else if (writing && mode < 0)
            indicator = steps[(bank * 16 + slot) * 16 + i] >= 0 || (v[RUN] && v[HEAD] == i);
        else if (mode < 0 || mode == TEMPO)
            indicator = (v[LIGHTS] & (1 << i)) != 0;
        lamp(i, indicator);
        snprintf(value, sizeof value, "%d", i + 1);
        SDL_Rect box = controls[i];
        box.y = labels[i].y;
        box.h = labels[i].h;
        text(box, 1, value,
             ((mode == RECORD && lengths[i]) || (mode == SOUND && i == slot) ||
              (mode == PATTERN && i == bank))
                 ? 0xff9147
                 : 0xf0efeb,
             1);
    }
    for (int i = SOUND; i <= WRITE; i++)
        lamp(i, i == mode || (i == DIAL_A + dial) || (i == WRITE && writing) ||
                    (i == EFFECT && fx_keys) || (i == PLAY && v[RUN]) ||
                    (i == RECORD && destination >= 0));
    knob(DIAL_A);
    knob(DIAL_B);
    text(labels[PLAY], 1, v[RUN] ? "stop" : "play", 0xefefeb, 1);
    text((SDL_Rect){417, 10, 46, 15}, 2, "exit", 0xaaa9a2, 1);
    if (inspecting) {
        if (!inspect_present(renderer, live_lamps, encoder_angle))
            say("3D UNAVAILABLE");
    } else
        SDL_RenderPresent(renderer);
}
static const SDL_Scancode laptop[16] = {SDL_SCANCODE_1, SDL_SCANCODE_2, SDL_SCANCODE_3, SDL_SCANCODE_4,
                                        SDL_SCANCODE_Q, SDL_SCANCODE_W, SDL_SCANCODE_E, SDL_SCANCODE_R,
                                        SDL_SCANCODE_A, SDL_SCANCODE_S, SDL_SCANCODE_D, SDL_SCANCODE_F,
                                        SDL_SCANCODE_Z, SDL_SCANCODE_X, SDL_SCANCODE_C, SDL_SCANCODE_V};
static const SDL_Scancode k0[16] = {
    SDL_SCANCODE_1, SDL_SCANCODE_2,    SDL_SCANCODE_KP_DIVIDE, SDL_SCANCODE_KP_MULTIPLY,
    SDL_SCANCODE_Q, SDL_SCANCODE_KP_7, SDL_SCANCODE_KP_8,      SDL_SCANCODE_KP_9,
    SDL_SCANCODE_A, SDL_SCANCODE_KP_4, SDL_SCANCODE_KP_5,      SDL_SCANCODE_KP_6,
    SDL_SCANCODE_Z, SDL_SCANCODE_KP_1, SDL_SCANCODE_KP_2,      SDL_SCANCODE_KP_3};
static int mapped(SDL_Scancode key) {
    for (int i = 0; i < 16; i++)
        if (key == laptop[i] || key == k0[i])
            return i;
    switch (key) {
    case SDL_SCANCODE_T:
        return SOUND;
    case SDL_SCANCODE_Y:
        return PATTERN;
    case SDL_SCANCODE_U:
        return TEMPO;
    case SDL_SCANCODE_I:
        return RECORD;
    case SDL_SCANCODE_KP_MINUS:
    case SDL_SCANCODE_MINUS:
        return EFFECT;
    case SDL_SCANCODE_KP_PLUS:
    case SDL_SCANCODE_SPACE:
        return PLAY;
    case SDL_SCANCODE_KP_ENTER:
    case SDL_SCANCODE_RETURN:
        return WRITE;
    case SDL_SCANCODE_KP_0:
        return RESET;
    case SDL_SCANCODE_ESCAPE:
        return EXIT;
    default:
        return -1;
    }
}
static int hit(int x, int y) {
    SDL_Point p = {x, y};
    for (int i = 0; i <= RESET; i++)
        if (SDL_PointInRect(&p, &controls[i]))
            return i;
    return x >= 415 && y < 30 ? EXIT : -1;
}
static int mouse_y, touch_y[3];
static SDL_FingerID fingers[3];
static int touch_used[3];
static void pointer_motion(int handle, int y, int *last) {
    int selected = down[handle] - 1;
    if (selected != DIAL_A && selected != DIAL_B)
        return;
    int delta = (*last - y) / 6;
    if (delta) {
        dial = selected == DIAL_B;
        turn(delta, 0);
        *last -= delta * 6;
    }
}
static void event(SDL_Event *e) {
    if (e->type == SDL_QUIT) {
        quit = 1;
        return;
    }
    bool was_3d = inspect_open();
    if (inspect_input(e)) {
        if (!was_3d && inspect_open()) {
            for (int i = 0; i < 4; i++)
                release(SDL_NUM_SCANCODES + i);
            memset(touch_used, 0, sizeof touch_used);
        }
        return;
    }
    if (e->type == SDL_WINDOWEVENT && e->window.event == SDL_WINDOWEVENT_FOCUS_LOST) {
        silence();
        cancel_take = 1;
        mode = -1;
        memset(touch_used, 0, sizeof touch_used);
        return;
    }
    if (e->type == SDL_KEYUP) {
        release(e->key.keysym.scancode);
        return;
    }
    if (e->type == SDL_KEYDOWN) {
        SDL_Scancode k = e->key.keysym.scancode;
        if (e->key.repeat || e->key.keysym.mod & (KMOD_CTRL | KMOD_ALT | KMOD_GUI))
            return;
        if (k == SDL_SCANCODE_LEFTBRACKET || k == SDL_SCANCODE_RIGHTBRACKET) {
            if (destination < 0)
                turn(k == SDL_SCANCODE_RIGHTBRACKET ? 1 : -1, 1);
        } else if (k == SDL_SCANCODE_O) {
            if (destination < 0) {
                dial = !dial;
                notice_until = 0;
                last_direction = 0;
            }
        } else if (k == SDL_SCANCODE_KP_PERIOD || k == SDL_SCANCODE_PERIOD) {
            quit = 1;
        } else
            press(mapped(k), k);
        return;
    }
    if (e->type == SDL_MOUSEBUTTONDOWN && e->button.button == SDL_BUTTON_LEFT) {
        mouse_y = e->button.y;
        press(hit(e->button.x, mouse_y), SDL_NUM_SCANCODES);
        return;
    }
    if (e->type == SDL_MOUSEMOTION) {
        pointer_motion(SDL_NUM_SCANCODES, e->motion.y, &mouse_y);
        return;
    }
    if (e->type == SDL_MOUSEBUTTONUP) {
        release(SDL_NUM_SCANCODES);
        return;
    }
    if (e->type == SDL_MOUSEWHEEL) {
        int x, y;
        SDL_GetMouseState(&x, &y);
        int i = hit(x, y);
        if ((i == DIAL_A || i == DIAL_B) && e->wheel.y) {
            dial = i == DIAL_B;
            turn(e->wheel.y > 0 ? 1 : -1, 0);
        }
        return;
    }
    if (e->type == SDL_FINGERDOWN || e->type == SDL_FINGERUP || e->type == SDL_FINGERMOTION) {
        int i = 0;
        while (i < 3 && (!touch_used[i] || fingers[i] != e->tfinger.fingerId))
            i++;
        int y = (int)(e->tfinger.y * 640);
        if (e->type == SDL_FINGERDOWN) {
            if (i == 3) {
                i = 0;
                while (i < 3 && touch_used[i])
                    i++;
                if (i == 3)
                    return;
            }
            touch_used[i] = 1;
            fingers[i] = e->tfinger.fingerId;
            touch_y[i] = y;
            press(hit((int)(e->tfinger.x * 480), y), SDL_NUM_SCANCODES + 1 + i);
        } else if (i < 3) {
            if (e->type == SDL_FINGERUP) {
                release(SDL_NUM_SCANCODES + 1 + i);
                touch_used[i] = 0;
            } else
                pointer_motion(SDL_NUM_SCANCODES + 1 + i, y, &touch_y[i]);
        }
    }
}
static float energy(const float *p, int n) {
    float sum = 0;
    for (int i = 0; i < n; i++)
        sum += fabsf(p[i]);
    return sum;
}
static int selftest(void) {
    reset();
    for (dial = 0; dial < 2; dial++) {
        for (int i = 0; i < 49; i++)
            turn(1, 0);
        if (encoder_angle[dial] != 15 || (dial ? levels[8] : pitches[8 * 16]) != (dial ? 100 : 12))
            return 8;
        turn(-1, 0);
        if (encoder_angle[dial] != 0 || (dial ? levels[8] : pitches[8 * 16]) != (dial ? 95 : 11))
            return 9;
        for (int i = 0; i < 49; i++)
            turn(-1, 0);
        if (encoder_angle[dial] != -15 || (dial ? levels[8] : pitches[8 * 16]) != (dial ? 0 : -12))
            return 10;
        turn(0, 0);
        if (encoder_angle[dial] != 0)
            return 11;
    }
    reset();
    turn(1, 0);
    if (meter_bars(0, SDL_GetTicks()) != 26 || meter_bars(0, notice_until) != 0)
        return 12;
    dial = 1;
    turn(1, 0);
    if (meter_bars(0, SDL_GetTicks()) != 26 || meter_bars(1000, notice_until) != 48)
        return 13;
    dial = 0;
    mode = TEMPO;
    turn(1, 0);
    if (meter_bars(0, SDL_GetTicks()) != 10)
        return 14;
    puts("PASS temporary pitch, volume and BPM meter; timed return to output level");
    puts("PASS native encoders rotate multiple revolutions through both limits");
    float block[2 * BLOCK];
    reset();
    audio_block(NULL, (Uint8 *)block, sizeof block);
    if (energy(block, 2 * BLOCK) != 0)
        return 1;
    note(0);
    note(1);
    audio_block(NULL, (Uint8 *)block, sizeof block);
    if (energy(block, 2 * BLOCK) < 0.1f || s[LIGHTS] != 3)
        return 2;
    // Synthetic two-tone capture exercises both ends of the slot and per-pad tuning.
    reset();
    s[SLOT] = 1;
    lengths[1] = RATE * 8;
    for (int i = 0; i < TAKE; i++)
        takes[TAKE + i] = 0.4f * sinf(6.2831853f * (i < RATE * 4 ? 440 : 740) * i / RATE);
    for (int pad = 0; pad < 16; pad++) {
        silence();
        note(pad);
        int crosses = 0;
        float prev = 0;
        for (int b = 0; b < 20; b++) {
            audio_block(NULL, (Uint8 *)block, sizeof block);
            for (int i = 0; i < BLOCK; i++) {
                if (prev < 0 && block[2 * i] >= 0)
                    crosses++;
                prev = block[2 * i];
            }
        }
        int hz = crosses * RATE / (20 * BLOCK);
        if (abs(hz - (pad < 8 ? 440 : 740)) > 12)
            return 3;
    }
    reset();
    int previous = -1, changes = 0;
    double fingerprints[17];
    Uint64 worst = 0, total = 0;
    int blocks = 0;
    for (int effect = -1; effect < 16; effect++) {
        reset();
        transport();
        s[FX] = effect;
        double fp = 0;
        for (int i = 0; i < 282; i++) {
            Uint64 start = SDL_GetPerformanceCounter();
            audio_block(NULL, (Uint8 *)block, sizeof block);
            Uint64 elapsed = SDL_GetPerformanceCounter() - start;
            if (elapsed > worst)
                worst = elapsed;
            total += elapsed;
            blocks++;
            if (s[HEAD] != previous) {
                previous = s[HEAD];
                changes++;
            }
            for (int j = 0; j < 2 * BLOCK; j++) {
                if (!isfinite(block[j]))
                    return 4;
                fp += fabs(block[j]) * (1 + (j % 13) * 0.01);
            }
        }
        if (fp < 1)
            return 5;
        for (int i = 0; i <= effect; i++)
            if (fabs(fp - fingerprints[i]) < 0.001)
                return 6;
        fingerprints[effect + 1] = fp;
    }
    if (changes < 100)
        return 7;
    printf("PASS Mojo polyphony; 16 recorded slices; transport; 16 distinct FX. Mean %.3f ms, worst "
           "%.3f ms per %d-frame block (%.3f ms budget).\n",
           (double)total / blocks * 1000 / SDL_GetPerformanceFrequency(),
           (double)worst * 1000 / SDL_GetPerformanceFrequency(), BLOCK, BLOCK * 1000.0 / RATE);
    return 0;
}
int main(int argc, char **argv) {
    int test = argc == 2 && strcmp(argv[1], "--self-test") == 0;
    int io = argc == 2 && strcmp(argv[1], "--verify-io") == 0;
    if (argc > 1 && !test && !io) {
        fprintf(stderr, "usage: bap [--self-test|--verify-io]\n");
        return 64;
    }
    size_t n = 0;
    factory = read_file("factory.f32", &n);
    if (!factory || n != (size_t)(wave_offsets[255] + wave_lengths[255]) * sizeof(float)) {
        fprintf(stderr, "B.A.P.: missing or invalid factory bank\n");
        return 2;
    }
    if (test)
        return selftest();
    // Prevent a second desktop click from opening a competing audio session.
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    char lockpath[512];
    int lockfd = -1;
    if (runtime) {
        snprintf(lockpath, sizeof lockpath, "%s/torque-bap.lock", runtime);
        lockfd = open(lockpath, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
        if (lockfd < 0) {
            perror("B.A.P. lock");
            return 2;
        }
        if (flock(lockfd, LOCK_EX | LOCK_NB) < 0) {
            fprintf(stderr, "B.A.P. already open\n");
            return 1;
        }
    }
    SDL_SetHint(SDL_HINT_TOUCH_MOUSE_EVENTS, "0");
    SDL_SetHint(SDL_HINT_MOUSE_TOUCH_EVENTS, "0");
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "1");
    SDL_SetHint(SDL_HINT_VIDEO_X11_FORCE_EGL, "1");
    if (SDL_Init(SDL_INIT_AUDIO | SDL_INIT_TIMER | (io ? 0 : SDL_INIT_VIDEO))) {
        fprintf(stderr, "%s\n", SDL_GetError());
        return 2;
    }
    reset();
    output = open_audio(0);
    if (!output) {
        if (!io)
            SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "B.A.P.", "Carrier Line Out is unavailable.",
                                     NULL);
        SDL_Quit();
        return 3;
    }
    SDL_PauseAudioDevice(output, 0);
    if (io) {
        input = open_audio(1);
        if (!input) {
            SDL_Quit();
            return 4;
        }
        SDL_PauseAudioDevice(input, 0);
        SDL_Delay(700);
        Uint32 bytes = SDL_GetQueuedAudioSize(input);
        printf(
            "Selected input delivered %u mono frames; discarded, no take saved. Output was silent.\n",
            bytes / (unsigned)sizeof(float));
        SDL_CloseAudioDevice(input);
        SDL_CloseAudioDevice(output);
        SDL_Quit();
        return bytes ? 0 : 5;
    }
    SDL_SetHint(SDL_HINT_RENDER_DRIVER, "opengles2");
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_ES);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 2);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 0);
    window = SDL_CreateWindow("B.A.P. - Torque", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 480,
                              640, SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_OPENGL);
    if (window)
        renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED);
    if (window && !renderer)
        renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    if (!renderer || SDL_RenderSetLogicalSize(renderer, 480, 640) || !skin()) {
        fprintf(stderr, "B.A.P. display: %s\n", SDL_GetError());
        SDL_Quit();
        return 6;
    }
    SDL_ShowCursor(SDL_DISABLE);
    if (SDL_ShowCursor(SDL_QUERY) != SDL_DISABLE) {
        fprintf(stderr, "B.A.P.: could not hide the pointer\n");
        SDL_Quit();
        return 6;
    }
    fprintf(stderr, "B.A.P. ready\n");
    unsigned next_draw = 0;
    while (!quit) {
        SDL_Event e;
        if (SDL_WaitEventTimeout(&e, 4)) {
            SDL_LockAudioDevice(output);
            event(&e);
            SDL_UnlockAudioDevice(output);
            while (SDL_PollEvent(&e)) {
                SDL_LockAudioDevice(output);
                event(&e);
                SDL_UnlockAudioDevice(output);
            }
        }
        capture_pump();
        unsigned now = SDL_GetTicks();
        if (SDL_TICKS_PASSED(now, next_draw)) {
            draw();
            next_draw = now + 32;
        }
    }
    if (input)
        SDL_CloseAudioDevice(input);
    SDL_CloseAudioDevice(output);
    SDL_ShowCursor(SDL_ENABLE);
    inspect_shutdown();
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    if (lockfd >= 0)
        close(lockfd);
    free(factory);
    return 0;
}
