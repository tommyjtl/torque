/* Native platform boundary. Mojo owns the game rules, timing and level traversal. */
#define SDL_MAIN_HANDLED
#include <SDL.h>
#include <SDL_opengl.h>
#include <SDL_opengl_glext.h>
#include <dlfcn.h>
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#ifdef __APPLE__
#include <CommonCrypto/CommonDigest.h>
#include <mach-o/dyld.h>
#endif

enum { W = 320, H = 200, MAT = 6, LEVELS = 8 };
extern int switchyard_run(uint8_t *, int32_t, uint32_t *, float *, int32_t *, int32_t *, int32_t,
                          int32_t, int32_t);
static uint32_t pixels[W * H], wad_hash;
static float depth[W * H], audio_pcm[4096];
static int32_t *state, *scratch;
static int campaign_map, skill = 3;
int cl_skill(void) { return skill; }
int cl_map(void) { return campaign_map; }
static const char *save_path = ".switchyard.sav", *capture_path, *legacy_path = ".hangar.sav";
static int fullscreen, hidden, no_audio, mouse_dx, mode_gpu, failed, check_memory;
static uint32_t *memory_save, *save_buffer;
static int payload_words = 9;
static int saved;
static unsigned frame_count, key_presses, key_releases, motion_events, clicks, tones;
static unsigned histogram[501]; /* 1 ms buckets after the first second; 500+ ms last. */
static double opened, last_flip;
static unsigned empty_audio_queue_events;
static SDL_Window *window;
static SDL_Renderer *renderer;
static SDL_Texture *screen_texture;
static SDL_GLContext context;
static SDL_AudioDeviceID speaker;
static void *sdl;
#define SDL_API(F)                                                                                 \
    F(Init)                                                                                        \
    F(Quit)                                                                                        \
    F(GetVersion)                                                                                  \
    F(GetError)                                                                                    \
    F(CreateWindow)                                                                                \
    F(DestroyWindow)                                                                               \
    F(GetWindowSize)                                                                               \
    F(PollEvent) F(SetRelativeMouseMode) F(CreateRenderer) F(DestroyRenderer) F(CreateTexture)     \
        F(DestroyTexture) F(UpdateTexture) F(RenderClear) F(RenderCopy) F(RenderPresent)           \
            F(GL_SetAttribute) F(GL_CreateContext) F(GL_DeleteContext) F(GL_GetProcAddress)        \
                F(GL_SetSwapInterval) F(GL_SwapWindow) F(GL_GetDrawableSize)                       \
                    F(GetCurrentAudioDriver) F(GetAudioDeviceName) F(GetNumAudioDevices)           \
                        F(OpenAudioDevice) F(CloseAudioDevice) F(PauseAudioDevice)                 \
                            F(ClearQueuedAudio) F(QueueAudio) F(GetQueuedAudioSize) F(Delay)
#define FUNC_DECL(n) static __typeof__(SDL_##n) *api_##n;
SDL_API(FUNC_DECL)
static int load_sdl(void) {
#ifdef __APPLE__
    const char *names[] = {"libSDL2-2.0.0.dylib", "/opt/homebrew/opt/sdl2/lib/libSDL2.dylib", NULL};
#else
    const char *names[] = {"libSDL2-2.0.so.0", NULL};
#endif
    for (int i = 0; names[i] && !sdl; ++i)
        sdl = dlopen(names[i], RTLD_NOW | RTLD_LOCAL);
    if (!sdl) {
        fprintf(stderr, "SDL2 runtime unavailable: %s\n", dlerror());
        return 0;
    }
#define LOAD_SDL(n)                                                                                \
    if (!(api_##n = dlsym(sdl, "SDL_" #n))) {                                                      \
        fprintf(stderr, "SDL2 missing %s\n", #n);                                                  \
        return 0;                                                                                  \
    }
    SDL_API(LOAD_SDL)
    SDL_version v;
    api_GetVersion(&v);
    if (v.major != 2)
        return 0;
    fprintf(stderr, "SDL %u.%u.%u\n", v.major, v.minor, v.patch);
    return 1;
}
double sw_clock(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static uint32_t hash(const void *data, size_t size) {
    const uint8_t *p = data;
    uint32_t h = 2166136261u;
    while (size--)
        h = (h ^ *p++) * 16777619u;
    return h;
}
int sw_save(int32_t *payload) {
    uint32_t *buf = save_buffer;
    buf[0] = 0x31595753;
    buf[1] = campaign_map ? (uint32_t)(4 + 256 * campaign_map) : 1;
    buf[2] = wad_hash;
    size_t bytes = 4 * (payload_words + 4);
    memcpy(buf + 3, payload, payload_words * 4);
    buf[payload_words + 3] = hash(buf, bytes - 4);
    if (check_memory) {
        memcpy(memory_save, buf, bytes);
        saved = 1;
        return 1;
    }
    char tmp[4096];
    if (snprintf(tmp, sizeof tmp, "%s.XXXXXX", save_path) >= (int)sizeof tmp)
        return 0;
    int fd = mkstemp(tmp);
    if (fd < 0)
        return 0;
    int ok = write(fd, buf, bytes) == (ssize_t)bytes && fsync(fd) == 0;
    if (close(fd))
        ok = 0;
    if (ok && !rename(tmp, save_path))
        return 1;
    unlink(tmp);
    return 0;
}
int sw_load(int32_t *payload) {
    uint32_t *buf = save_buffer;
    size_t bytes = 4 * (payload_words + 4);
    if (check_memory) {
        if (!saved)
            return 0;
        memcpy(buf, memory_save, bytes);
    } else {
        FILE *f = fopen(save_path, "rb");
        if (!f)
            return 0;
        int ok = fread(buf, 1, bytes, f) == bytes && fgetc(f) == EOF;
        fclose(f);
        if (!ok)
            return 0;
    }
    if (buf[0] != 0x31595753 || buf[1] != (campaign_map ? (uint32_t)(4 + 256 * campaign_map) : 1) ||
        buf[2] != wad_hash || buf[payload_words + 3] != hash(buf, bytes - 4))
        return 0;
    memcpy(payload, buf + 3, payload_words * 4);
    return 1;
}
/* Tick commands use the same movement and action units as desktop input. */
static FILE *replay;
static int32_t command[4];
static int ticks_remaining;
void *sw_replay_buffer(void) { return command; }
static void report_replay_boundary(void);
int sw_next_command(void) {
    report_replay_boundary();
    while (ticks_remaining == 0) {
        char line[128], trailing;
        if (!fgets(line, sizeof line, replay))
            return ferror(replay) ? -1 : 0;
        if (line[0] == '#' || line[0] == '\n')
            continue;
        if (!strncmp(line, "expect ", 7)) {
            int map, exit_code;
            if (sscanf(line, "expect E1M%d %d %c", &map, &exit_code, &trailing) != 2 ||
                map != campaign_map || state[6] != exit_code) {
                fprintf(stderr, "Replay boundary: expected %sactual E1M%d exit=%d\n", line + 7,
                        campaign_map, state[6]);
                return -1;
            }
            printf("verified E1M%d exit=%d state=%08x\n", map, exit_code,
                   hash(state, payload_words * 4));
            continue;
        }
        if (!strcmp(line, "restorepoint\n"))
            return 2;
        if (!strcmp(line, "checkpoint\n")) {
            if (!sw_save(state))
                return -1;
            printf("checkpoint map=%d tic=%d\n", campaign_map, state[7]);
            fflush(stdout);
            continue;
        }
        int n = sscanf(line, "%d %d %d %d %d %c", &ticks_remaining, &command[0], &command[1],
                       &command[2], &command[3], &trailing);
        if (n != 5 || ticks_remaining < 1 || ticks_remaining > 100000 || command[0] < -1 ||
            command[0] > 1 || command[1] < -1 || command[1] > 1 || command[2] < -4096 ||
            command[2] > 4096 || command[3] < 0 || command[3] > 63)
            return -1;
    }
    --ticks_remaining;
    return 1;
}
int cl_combat_report(int kills, int living, int awake, int health, int missiles) {
    printf("kills=%d living=%d awake=%d health=%d missiles=%d map=E%dM%d\n", kills, living, awake,
           health, missiles, (campaign_map - 1) / 9 + 1, (campaign_map - 1) % 9 + 1);
    return 0;
}

static void ppm(const uint32_t *p) {
    if (!capture_path)
        return;
    FILE *f = fopen(capture_path, "wb");
    if (!f) {
        perror(capture_path);
        failed = 1;
        return;
    }
    fprintf(f, "P6\n%d %d\n255\n", W, H);
    for (int i = 0; i < W * H; i++) {
        fputc((p[i] >> 16) & 255, f);
        fputc((p[i] >> 8) & 255, f);
        fputc(p[i] & 255, f);
    }
    if (fclose(f))
        failed = 1;
}
int sw_report(int32_t *s, uint32_t *p, int frames, int ticks) {
    if (!frames)
        ppm(p);
    double elapsed = opened ? sw_clock() - opened : 0;
    printf("backend=%s frames=%d ticks=%d wall=%.3f loop_hz=%.2f state=%08x "
           "position=(%.1f,%.1f) door=%d %s=%d exit=%d\n",
           frames ? (mode_gpu ? "gpu" : "cpu") : "headless", frames, ticks, elapsed,
           elapsed > 0 ? frames / elapsed : 0, hash(s, payload_words * 4), s[0] / 256., s[1] / 256.,
           s[3], campaign_map ? "ammo" : "signal", s[5], s[6]);
    if (frames) {
        unsigned total = 0, sum = 0, p95 = 0, median = 0;
        for (int i = 0; i <= 500; i++)
            total += histogram[i];
        for (int i = 0; i <= 500; i++) {
            sum += histogram[i];
            if (!median && sum * 2 >= total)
                median = i;
            if (sum * 100 >= total * 95) {
                p95 = i;
                break;
            }
        }
        struct rusage usage;
        getrusage(RUSAGE_SELF, &usage);
        long rss_kib = usage.ru_maxrss;
#ifdef __APPLE__
        rss_kib /= 1024;
#endif
        printf("median_ms_bucket=%u rss_kib=%ld empty_audio_queue_events=%u ", median, rss_kib,
               empty_audio_queue_events);
        printf("interval_samples=%u p95_ms_bucket=%u cpu_seconds=%.3f key_down=%u key_up=%u "
               "motion_events=%u left_click=%u audio_blocks=%u\n",
               total, p95,
               usage.ru_utime.tv_sec + usage.ru_stime.tv_sec +
                   (usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) * 1e-6,
               key_presses, key_releases, motion_events, clicks, tones);
    }
    return 0;
}
int sw_event(void) {
    SDL_Event e;
    while (api_PollEvent(&e)) {
        switch (e.type) {
        case SDL_QUIT:
            return 1;
        case SDL_KEYDOWN:
            if (!e.key.repeat) {
                key_presses++;
                return 1000 + e.key.keysym.scancode;
            }
            break;
        case SDL_KEYUP:
            key_releases++;
            return 2000 + e.key.keysym.scancode;
        case SDL_MOUSEBUTTONDOWN:
            if (e.button.button == SDL_BUTTON_LEFT) {
                clicks++;
                return 3;
            }
            break;
        case SDL_MOUSEBUTTONUP:
            if (e.button.button == SDL_BUTTON_LEFT)
                return 5;
            break;
        case SDL_MOUSEMOTION:
            motion_events++;
            mouse_dx = e.motion.xrel;
            return 4;
        case SDL_WINDOWEVENT:
            if (e.window.event == SDL_WINDOWEVENT_CLOSE)
                return 1;
            if (e.window.event == SDL_WINDOWEVENT_FOCUS_LOST)
                return 2;
            break;
        }
    }
    return 0;
}
int sw_mouse_dx(void) { return mouse_dx; }
int sw_capture(int enable) {
    return !hidden && api_SetRelativeMouseMode(enable ? SDL_TRUE : SDL_FALSE) == 0;
}
float *sw_audio_buffer(void) { return audio_pcm; }
int sw_audio(int samples) {
    if (!speaker || samples < 1 || samples > (campaign_map ? 2048 : 4096) ||
        api_GetQueuedAudioSize(speaker) > 32768)
        return 0;
    if (api_QueueAudio(speaker, audio_pcm, samples * (campaign_map ? 2 : 1) * sizeof(float)) != 0)
        return 0;
    tones++;
    return 1;
}

/* GL 2.1 entry points resolved against the context created by SDL. */
#define GL_API(F)                                                                                  \
    F(GetString)                                                                                   \
    F(CreateShader)                                                                                \
    F(ShaderSource)                                                                                \
    F(CompileShader)                                                                               \
    F(GetShaderiv)                                                                                 \
    F(GetShaderInfoLog)                                                                            \
    F(CreateProgram)                                                                               \
    F(AttachShader) F(BindAttribLocation) F(LinkProgram) F(GetProgramiv) F(GetProgramInfoLog)      \
        F(UseProgram) F(GetUniformLocation) F(Uniform4f) F(Uniform1i) F(BlendFunc)                 \
            F(DeleteTextures) F(GenTextures) F(BindTexture) F(TexImage2D) F(TexSubImage2D)         \
                F(TexParameteri) F(GenBuffers) F(BindBuffer) F(BufferData)                         \
                    F(EnableVertexAttribArray) F(VertexAttribPointer) F(DrawArrays) F(Enable)      \
                        F(Disable) F(ClearColor) F(Clear) F(Viewport) F(ReadPixels) F(GetError)    \
                            F(DeleteShader)
#define GL_DECL(n) static __typeof__(gl##n) *g##n;
GL_API(GL_DECL)
static GLuint program, buffer, textures[MAT * LEVELS], overlay;
static GLint pose_loc, overlay_loc, style_loc, sky_loc, rect_loc;
static int vx, vy, vw, vh;
static const char *vs =
    "#version 120\nattribute vec3 point; attribute vec2 uv; varying vec2 tc; uniform vec4 "
    "pose;uniform int overlayMode;"
    "void main(){tc=uv;if(overlayMode!=0){gl_Position=vec4(point.xy,0,1);return;}"
    "vec2 v=point.xy-pose.xy;float d=dot(v,pose.zw);float side=dot(v,vec2(pose.w,-pose.z));"
    "gl_Position=vec4(side,(point.z-40.)*1.3333333+.15*d,1.0005*d-1.00025,d);}";
static const char *fs =
    "#version 120\nuniform sampler2D atlas; varying vec2 tc; uniform int style; "
    "uniform vec4 sky; uniform vec4 rect;"
    "void main(){vec2 st=tc;vec2 xy=(gl_FragCoord.xy-rect.xy)/max(rect.zw,vec2(1));"
    "if(style==1)st=vec2((atan(xy.x*2.-1.)-sky.x)*.63661977,(100.+(1.-xy.y)*200.-85.)/128.);"
    "vec4 c=texture2D(atlas,st).bgra;if(c.a<.5)discard;"
    "if(style>1){if(mod(floor(xy.x*320.)+floor(xy.y*200.)+float(style),3.)<1.)discard;"
    "c=vec4(.015,.015,.018,.55);}gl_FragColor=c;}";
static GLuint shader(GLenum kind, const char *src) {
    GLuint id = gCreateShader(kind);
    gShaderSource(id, 1, &src, NULL);
    gCompileShader(id);
    GLint ok = 0;
    gGetShaderiv(id, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char msg[1024];
        gGetShaderInfoLog(id, sizeof msg, NULL, msg);
        fprintf(stderr, "%s\n", msg);
        return 0;
    }
    return id;
}
static GLuint texture(int w, int h, const uint32_t *data, int repeat) {
    GLuint tex;
    gGenTextures(1, &tex);
    gBindTexture(GL_TEXTURE_2D, tex);
    gTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    gTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    gTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, repeat ? GL_REPEAT : GL_CLAMP_TO_EDGE);
    gTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, repeat ? GL_REPEAT : GL_CLAMP_TO_EDGE);
    gTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data);
    return tex;
}
static int gl_init(void) {
#define LOAD_GL(n)                                                                                 \
    if (!(g##n = api_GL_GetProcAddress("gl" #n))) {                                                \
        fprintf(stderr, "Missing GL function gl%s\n", #n);                                         \
        return 0;                                                                                  \
    }
    GL_API(LOAD_GL)
    const char *name = (const char *)gGetString(GL_RENDERER);
    fprintf(stderr, "OpenGL: %s / %s\n", name, gGetString(GL_VERSION));
    if (!name || strstr(name, "llvmpipe") || strstr(name, "softpipe") ||
        strstr(name, "Software Rasterizer")) {
        fprintf(stderr, "GPU requested; software driver selected.\n");
        return 0;
    }
    GLuint vert = shader(GL_VERTEX_SHADER, vs), frag = shader(GL_FRAGMENT_SHADER, fs);
    if (!vert || !frag)
        return 0;
    program = gCreateProgram();
    gAttachShader(program, vert);
    gAttachShader(program, frag);
    gBindAttribLocation(program, 0, "point");
    gBindAttribLocation(program, 1, "uv");
    gLinkProgram(program);
    GLint ok = 0;
    gGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (!ok) {
        char msg[1024];
        gGetProgramInfoLog(program, sizeof msg, NULL, msg);
        fprintf(stderr, "%s\n", msg);
        return 0;
    }
    gDeleteShader(vert);
    gDeleteShader(frag);
    gUseProgram(program);
    pose_loc = gGetUniformLocation(program, "pose");
    overlay_loc = gGetUniformLocation(program, "overlayMode");
    style_loc = gGetUniformLocation(program, "style");
    rect_loc = gGetUniformLocation(program, "rect");
    sky_loc = gGetUniformLocation(program, "sky");
    gGenBuffers(1, &buffer);
    gBindBuffer(GL_ARRAY_BUFFER, buffer);
    gEnableVertexAttribArray(0);
    gEnableVertexAttribArray(1);
    gVertexAttribPointer(0, 3, GL_FLOAT, 0, 5 * sizeof(float), 0);
    gVertexAttribPointer(1, 2, GL_FLOAT, 0, 5 * sizeof(float), (void *)(3 * sizeof(float)));
    overlay = texture(W, H, NULL, 0);
    api_GL_SetSwapInterval(1);
    return gGetError() == GL_NO_ERROR;
}
int sw_open(int gpu) {
    mode_gpu = gpu;
    if (!load_sdl())
        return 0;
    if (api_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS))
        goto error;
    if (gpu) {
        api_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 2);
        api_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 1);
        api_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 24);
        api_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
    }
    unsigned flags = (fullscreen ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0) |
                     (hidden ? SDL_WINDOW_HIDDEN : 0) | (gpu ? SDL_WINDOW_OPENGL : 0);
    window = api_CreateWindow(campaign_map ? "DOOM Hangar | 0 exits" : "Switchyard | 0 exits",
                              SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 640, 480, flags);
    if (!window)
        goto error;
    if (gpu) {
        context = api_GL_CreateContext(window);
        if (!context || !gl_init())
            goto error;
    } else {
        renderer = api_CreateRenderer(window, -1, 0);
        if (!renderer)
            goto error;
        screen_texture = api_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888,
                                           SDL_TEXTUREACCESS_STREAMING, W, H);
        if (!screen_texture)
            goto error;
    }
    if (!no_audio) {
        SDL_AudioSpec want = {0};
        want.freq = 22050;
        want.format = AUDIO_F32SYS;
        want.channels = campaign_map ? 2 : 1;
        want.samples = 512;
        if (api_Init(SDL_INIT_AUDIO) == 0)
            speaker = api_OpenAudioDevice(NULL, 0, &want, NULL, 0);
        if (speaker) {
            fprintf(stderr, "SDL output open: %s, float32 / 22050 Hz\n",
                    api_GetCurrentAudioDriver());
            if (api_GetNumAudioDevices(0) == 1 &&
                !strcmp(api_GetAudioDeviceName(0, 0), "Dummy Output"))
                fprintf(stderr, "Only Dummy Output is available. Connect an audio device for "
                                "audible playback.\n");
            api_PauseAudioDevice(speaker, 0);
        } else
            fprintf(stderr, "Audio unavailable: %s\n", api_GetError());
    }
    fprintf(stderr, "K0 controls: 8/2 move, 4/6 turn, 7/9 strafe, 5 fire, Enter use, "
                    "+ save, - load, / help, 0 or Backspace exit.\n");
    opened = last_flip = sw_clock();
    return 1;
error:
    fprintf(stderr, "Window/graphics initialization failed: %s\n", api_GetError());
    return 0;
}
static void fit_rect(int w, int h, int *x, int *y, int *rw, int *rh) {
    *rw = (w * 3 <= h * 4) ? w : h * 4 / 3;
    *rh = *rw * 3 / 4;
    *x = (w - *rw) / 2;
    *y = (h - *rh) / 2;
}
int sw_texture(int mat, int light, const uint32_t *data) {
    textures[mat * LEVELS + light] = texture(64, 64, data, 1);
    return 0;
}
int sw_camera(float x, float y, float angle) {
    int w, h;
    api_GL_GetDrawableSize(window, &w, &h);
    fit_rect(w, h, &vx, &vy, &vw, &vh);
    gViewport(vx, vy, vw, vh);
    gClearColor(.04f, .06f, .07f, 1);
    gClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    gEnable(GL_DEPTH_TEST);
    gUniform1i(overlay_loc, 0);
    gUniform1i(style_loc, 0);
    gUniform4f(rect_loc, (float)vx, (float)vy, (float)vw, (float)vh);
    gUniform4f(sky_loc, angle, 0, 0, 0);
    gUniform4f(pose_loc, x, y, cosf(angle), sinf(angle));
    return 0;
}
typedef struct {
    float x, y, z, u, v;
} Vertex;
static void draw(GLuint tex, const Vertex v[4]) {
    gBindTexture(GL_TEXTURE_2D, tex);
    gBufferData(GL_ARRAY_BUFFER, 4 * sizeof(Vertex), v, GL_STREAM_DRAW);
    gDrawArrays(GL_TRIANGLE_FAN, 0, 4);
}
int sw_flat(int mat, int light, float ax, float ay, float bx, float by, float z) {
    Vertex v[] = {{ax, ay, z, ax / 64, ay / 64},
                  {ax, by, z, ax / 64, by / 64},
                  {bx, by, z, bx / 64, by / 64},
                  {bx, ay, z, bx / 64, ay / 64}};
    draw(textures[mat * LEVELS + light], v);
    return 0;
}
int sw_wall(int mat, int light, float ax, float ay, float bx, float by, float lo, float hi,
            float width) {
    float u = width / 64, top = (96 - hi) / 64, bottom = (96 - lo) / 64;
    if (mat == 5) {
        top = 0;
        bottom = 1;
        u = 1;
    }
    Vertex v[] = {{ax, ay, lo, 0, bottom},
                  {bx, by, lo, u, bottom},
                  {bx, by, hi, u, top},
                  {ax, ay, hi, 0, top}};
    draw(textures[mat * LEVELS + light], v);
    return 0;
}
static int gl_capture(void) {
    if (vw <= 0 || vh <= 0 || vw > 8192 || vh > 8192)
        return 0;
    uint8_t *buf = malloc((size_t)vw * vh * 4);
    if (!buf)
        return 0;
    gReadPixels(vx, vy, vw, vh, GL_RGBA, GL_UNSIGNED_BYTE, buf);
    FILE *f = fopen(capture_path, "wb");
    if (!f) {
        free(buf);
        return 0;
    }
    fprintf(f, "P6\n%d %d\n255\n", vw, vh);
    for (int y = vh - 1; y >= 0; y--)
        for (int x = 0; x < vw; x++)
            fwrite(buf + 4 * ((size_t)y * vw + x), 1, 3, f);
    free(buf);
    return fclose(f) == 0;
}
int sw_present(const uint32_t *p, int gpu) {
    if (gpu) {
        gDisable(GL_DEPTH_TEST);
        gUniform1i(overlay_loc, 1);
        gUniform1i(style_loc, 0);
        gBindTexture(GL_TEXTURE_2D, overlay);
        gTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, p);
        Vertex v[] = {{-1, 1, 0, 0, 0}, {-1, -1, 0, 0, 1}, {1, -1, 0, 1, 1}, {1, 1, 0, 1, 0}};
        draw(overlay, v);
        if (capture_path && frame_count == 0 && !gl_capture())
            failed = 1;
        api_GL_SwapWindow(window);
    } else {
        int w, h;
        api_GetWindowSize(window, &w, &h);
        SDL_Rect dst;
        fit_rect(w, h, &dst.x, &dst.y, &dst.w, &dst.h);
        if (api_UpdateTexture(screen_texture, NULL, p, W * 4) || api_RenderClear(renderer) ||
            api_RenderCopy(renderer, screen_texture, NULL, &dst))
            failed = 1;
        api_RenderPresent(renderer);
        if (capture_path && !frame_count)
            ppm(p);
    }
    frame_count++;
    double left = 1. / 60 - (sw_clock() - last_flip);
    if (left > .001)
        api_Delay((Uint32)(left * 1000));
    double now = sw_clock();
    if (now - opened > 1)
        histogram[(int)fmin(500, ceil((now - last_flip) * 1000))]++;
    last_flip = now;
    return 0;
}
static void cleanup(void) {
    if (!sdl || !api_Quit)
        return;
    if (speaker)
        api_CloseAudioDevice(speaker);
    if (context)
        api_GL_DeleteContext(context);
    if (screen_texture)
        api_DestroyTexture(screen_texture);
    if (renderer)
        api_DestroyRenderer(renderer);
    if (window)
        api_DestroyWindow(window);
    api_Quit();
    dlclose(sdl);
}
#include "classic_platform.inc"

static void report_replay_boundary(void) {
    static int last_map, reported_exit, reported_death;
    int hp = state[11 + campaign_catalog[campaign_map - 1].sectors];
    if (last_map != campaign_map) {
        last_map = campaign_map;
        reported_exit = reported_death = 0;
    }
    if (state[6] && !reported_exit) {
        printf("completed E1M%d exit=%d state=%08x\n", campaign_map, state[6],
               hash(state, 4 * payload_words));
        reported_exit = 1;
    } else if (!state[6])
        reported_exit = 0;
    if (!hp && !state[6] && !reported_death) {
        printf("player died in E1M%d at tick %d\n", campaign_map, state[7]);
        reported_death = 1;
    } else if (hp > 0)
        reported_death = 0;
}

int main(int argc, char **argv) {
    const char *iwad = NULL, *index = NULL;
    int fixture = 0;
    char data_wad[4096], data_index[4096];
    int gpu = 0, flags = 0, seconds = 0, explicit_save = 0, map_number = 1;
    const char *wad = NULL;
#ifdef __linux__
    fullscreen = 1;
#endif
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--renderer=cpu"))
            gpu = 0;
        else if (!strcmp(a, "--renderer=gpu"))
            gpu = 1;
        else if (!strcmp(a, "--map") && i + 1 < argc) {
            const char *name = argv[++i];
            if (strlen(name) != 4 || name[0] != 'E' || name[1] != '1' || name[2] != 'M' ||
                name[3] < '1' || name[3] > '9')
                return 64;
            map_number = (name[1] - '1') * 9 + name[3] - '0';
        } else if (!strcmp(a, "--skill") && i + 1 < argc) {
            const char *number = argv[++i];
            if (strlen(number) != 1 || *number < '1' || *number > '5')
                return 64;
            skill = *number - '0';
        } else if (!strcmp(a, "--fixture"))
            fixture = 1;
        else if (!strcmp(a, "--replay") && i + 1 < argc) {
            const char *path = argv[++i];
            replay = !strcmp(path, "-") ? stdin : fopen(path, "r");
            if (!replay) {
                perror("replay");
                return 2;
            }
            flags |= 32;
        } else if (!strcmp(a, "--tour"))
            flags |= 1;
        else if (!strcmp(a, "--resume"))
            flags |= 2;
        else if (!strcmp(a, "--sample-render")) {
            flags |= 260;
            no_audio = 1;
        } else if (!strcmp(a, "--check-music"))
            flags |= 68;
        else if (!strcmp(a, "--check"))
            flags |= 4;
        else if (!strcmp(a, "--mute"))
            no_audio = 1;
        else if (!strcmp(a, "--windowed"))
            fullscreen = 0;
        else if (!strcmp(a, "--fullscreen"))
            fullscreen = 1;
        else if (!strcmp(a, "--hidden"))
            hidden = 1;
        else if (!strcmp(a, "--import-hangar") && i + 1 < argc) {
            legacy_path = argv[++i];
            flags |= 128;
        } else if (!strcmp(a, "--iwad") && i + 1 < argc)
            iwad = argv[++i];
        else if (!strcmp(a, "--index") && i + 1 < argc)
            index = argv[++i];
        else if (!strcmp(a, "--wad") && i + 1 < argc)
            wad = argv[++i];
        else if (!strcmp(a, "--save") && i + 1 < argc) {
            save_path = argv[++i];
            explicit_save = 1;
        } else if (!strcmp(a, "--capture") && i + 1 < argc)
            capture_path = argv[++i];
        else if (!strcmp(a, "--seconds") && i + 1 < argc) {
            char *end;
            long v = strtol(argv[++i], &end, 10);
            if (*end || v < 1 || v > 3600)
                return 64;
            seconds = (int)v;
        } else {
            puts("Switchyard [--renderer=cpu|gpu] [--fixture] [--wad FILE] [--iwad doom1.wad "
                 "--index "
                 "doom1.syi] [--map E1M1..E1M9] [--skill 1..5] [--save FILE] [--resume] "
                 "[--fullscreen|--windowed] [--mute] [--tour] [--seconds 1..3600] [--hidden] "
                 "[--capture FILE.ppm] [--import-hangar FILE] [--replay FILE|-] "
                 "[--check|--check-music|--sample-render]");
            return strcmp(a, "--help") ? 64 : 0;
        }
    }
    if (!iwad && !index && !fixture && !wad && !(flags & 4)) {
        const char *home = getenv("HOME");
        if (!home || !*home) {
            fprintf(stderr, "Choose --iwad and --index.\n");
            return 64;
        }
#ifdef __APPLE__
        const char *dir = "Library/Application Support/Switchyard";
#else
        const char *dir = ".local/share/switchyard";
#endif
        if (snprintf(data_wad, sizeof data_wad, "%s/%s/doom1.wad", home, dir) >=
                (int)sizeof data_wad ||
            snprintf(data_index, sizeof data_index, "%s/%s/doom1.syi", home, dir) >=
                (int)sizeof data_index)
            return 64;
        iwad = data_wad;
        index = data_index;
    }
    if ((flags & 128) && (!iwad || (flags & 2)))
        return 64;
    if ((flags & 256) && !replay)
        return 64;
    if (replay && (!iwad || fixture || (flags & 1)))
        return 64;
    if (iwad || index) {
        if (!iwad || !index || !prepare_classic(iwad, index, map_number))
            return 2;
        flags |= 16;

        if (!explicit_save)
            save_path = ".campaign.sav";
    }
    char path[4096] = {0};
    if (!wad) {
#ifdef __APPLE__
        uint32_t length = sizeof path;
        if (_NSGetExecutablePath(path, &length) != 0)
            return 1;
#else
        ssize_t n = readlink("/proc/self/exe", path, sizeof path - 1);
        if (n <= 0 || n >= (ssize_t)sizeof path - 1)
            return 1;
#endif
        char *slash = strrchr(path, '/');
        if (!slash)
            return 1;
        *slash = 0;
        if (strlen(path) + sizeof "/../assets/switchyard.wad" > sizeof path)
            return 1;
        strcat(path, "/../assets/switchyard.wad");
        wad = path;
    }
    FILE *f = fopen(wad, "rb");
    if (!f) {
        perror(wad);
        return 1;
    }
    if (fseek(f, 0, SEEK_END)) {
        fclose(f);
        return 1;
    }
    long n = ftell(f);
    if (n < 12 || n > 16 * 1024 * 1024 || fseek(f, 0, SEEK_SET)) {
        fclose(f);
        fprintf(stderr, "Unsupported WAD size\n");
        return 2;
    }
    uint8_t *data = malloc(n);
    if (!data || fread(data, 1, n, f) != (size_t)n) {
        free(data);
        fclose(f);
        return 2;
    }
    fclose(f);
    wad_hash = iwad ? hash(classic_wad, 4196020) : hash(data, n);
    if (!campaign_map)
        state_capacity = payload_words + 2; /* The fixture also has two transient HUD words. */
    state = calloc(state_capacity, sizeof *state);
    scratch = calloc(state_capacity, sizeof *scratch);
    save_buffer = calloc(state_capacity + 4, sizeof *save_buffer);
    memory_save = calloc(state_capacity + 4, sizeof *memory_save);
    if (!state || !scratch || !save_buffer || !memory_save)
        return 2;
    check_memory = (flags & 4) && !explicit_save;
    if ((flags & 1) && !seconds)
        seconds = 7;
    if ((flags & 1) && !(flags & 2) && explicit_save)
        flags |= 8;
    int code = switchyard_run(data, (int)n, pixels, depth, state, scratch, gpu, flags, seconds);
    if (code)
        fprintf(stderr, "Switchyard failed (%d): %s\n", code,
                code == 2   ? "unsupported or invalid test WAD"
                : code == 3 ? "incompatible or invalid save"
                : code == 4 ? "platform initialization failed"
                            : "simulation acceptance failed");
    if (iwad)
        fprintf(stderr, "Original DMX effects: DSPISTOL=%u DSDOROPN=%u DSSWTCHN=%u DSITEMUP=%u\n",
                counts[0], counts[1], counts[2], counts[3]);
    if (replay)
        fclose(replay);
    cleanup();
    free(data);
    free(classic_wad);
    free(classic_index);
    free(classic_texels);
    free(sound_sectors);
    free(classic_bases);
    free(classic_textures);
    free(state);
    free(scratch);
    free(save_buffer);
    free(memory_save);
    return code ? code : failed;
}
