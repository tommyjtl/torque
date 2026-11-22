#include "inspection.h"
#define SDL_USE_BUILTIN_OPENGL_DEFINITIONS
#include <SDL_opengles2.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { WIDTH = 480, HEIGHT = 640, MAX_BATCHES = 128, MAX_TEXTURES = 12 };
typedef struct {
    int32_t first, count, texture, lamp, rotor;
    float pivot[2], rgb[3], metal, rough, unlit;
} Batch;
typedef struct {
    float yaw, pitch, up, zoom;
} Pose;
static const Pose front = {0, 0, 0, 1}, placed = {1.32f, .19f, 1.3439035f, .93f};
enum Phase { FLAT, ENTERING, ORBIT, RETURNING, HOMING };
static enum Phase phase;
static Pose pose, from, to;
static float elapsed, duration;
static unsigned last_frame;
static bool dragging, from_touch, failed;
static SDL_FingerID finger;
static float last_x, last_y;

static SDL_Window *win;
static SDL_GLContext original, context;
static SDL_Texture *panel, *image;
static GLuint panel_id, image_id, fbo, depth, program, vbo, textures[MAX_TEXTURES];
static Batch batches[MAX_BATCHES];
static int batch_count, vertices;
static float lcd[4];
static GLuint ms_fbo, ms_color, ms_depth;
typedef void(GL_APIENTRY *StorageMS)(GLenum, GLsizei, GLenum, GLsizei, GLsizei);
typedef void(GL_APIENTRY *Blit)(GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLbitfield,
                                GLenum);
static Blit resolve_ms;
static GLint vp, eye, kind, tint, surface, rot, uvbox, shadow_strength;

static float bound(float x, float a, float b) { return fminf(fmaxf(x, a), b); }
static float mixf(float a, float b, float t) { return a + (b - a) * t; }
static void move(enum Phase next, Pose end, float ms) {
    from = pose;
    from.yaw = end.yaw + atan2f(sinf(from.yaw - end.yaw), cosf(from.yaw - end.yaw));
    to = end;
    phase = next;
    elapsed = 0;
    duration = ms;
    last_frame = 0;
    dragging = false;
}
bool inspect_open(void) { return phase != FLAT; }
void inspect_return(void) {
    if (phase != FLAT && phase != RETURNING)
        move(RETURNING, front, 520);
}
void inspect_toggle(void) {
    if (phase == FLAT) {
        pose = front;
        move(ENTERING, placed, 900);
    } else
        inspect_return();
}
static void orbit(float dx, float dy) {
    if (phase == RETURNING || (!dx && !dy))
        return;
    phase = ORBIT;
    pose.yaw -= dx * .009f;
    pose.pitch = bound(pose.pitch + dy * .009f, -1.48f, 1.48f);
}
bool inspect_input(const SDL_Event *e) {
    if (e->type == SDL_KEYDOWN && e->key.keysym.scancode == SDL_SCANCODE_P &&
        !(e->key.keysym.mod & (KMOD_CTRL | KMOD_ALT | KMOD_GUI))) {
        if (!e->key.repeat)
            inspect_toggle();
        return true;
    }
    if (!inspect_open())
        return false;
    if (e->type == SDL_WINDOWEVENT && e->window.event == SDL_WINDOWEVENT_FOCUS_LOST)
        dragging = false;
    if (e->type == SDL_KEYDOWN) {
        switch (e->key.keysym.scancode) {
        case SDL_SCANCODE_ESCAPE:
            inspect_return();
            return true;
        case SDL_SCANCODE_HOME:
            if (phase != RETURNING)
                move(HOMING, (Pose){0, 0, 0, 1.22f}, 420);
            return true;
        case SDL_SCANCODE_LEFT:
            orbit(19, 0);
            return true;
        case SDL_SCANCODE_RIGHT:
            orbit(-19, 0);
            return true;
        case SDL_SCANCODE_UP:
            orbit(0, 19);
            return true;
        case SDL_SCANCODE_DOWN:
            orbit(0, -19);
            return true;
        default:
            return false;
        }
    }
    switch (e->type) {
    case SDL_MOUSEBUTTONDOWN:
        if (e->button.button == SDL_BUTTON_LEFT && !dragging) {
            dragging = true;
            from_touch = false;
            last_x = e->button.x;
            last_y = e->button.y;
        }
        return true;
    case SDL_MOUSEBUTTONUP:
        if (!from_touch)
            dragging = false;
        return true;
    case SDL_MOUSEMOTION:
        if (dragging && !from_touch) {
            orbit(e->motion.x - last_x, e->motion.y - last_y);
            last_x = e->motion.x;
            last_y = e->motion.y;
        }
        return true;
    case SDL_MOUSEWHEEL:
        if (phase != RETURNING) {
            phase = ORBIT;
            pose.zoom = bound(pose.zoom * expf(-e->wheel.y * .10f), .8f, 2.45f);
        }
        return true;
    case SDL_FINGERDOWN:
        if (!dragging) {
            dragging = true;
            from_touch = true;
            finger = e->tfinger.fingerId;
        }
        return true;
    case SDL_FINGERMOTION:
        if (dragging && from_touch && finger == e->tfinger.fingerId)
            orbit(e->tfinger.dx * WIDTH, e->tfinger.dy * HEIGHT);
        return true;
    case SDL_FINGERUP:
        if (from_touch && finger == e->tfinger.fingerId)
            dragging = false;
        return true;
    default:
        return false;
    }
}
static const char vertex_shader[] =
    "attribute vec3 aP,aN; attribute vec2 aUV; uniform mat4 vp; uniform vec4 rotor; varying vec3 n,p; "
    "varying vec2 uv;"
    "void main(){mat2 "
    "r=mat2(rotor.z,rotor.w,-rotor.w,rotor.z);p=vec3(r*(aP.xy-rotor.xy)+rotor.xy,aP.z);"
    "n=vec3(r*aN.xy,aN.z);uv=aUV;gl_Position=vp*vec4(p,1.);gl_Position.y=-gl_Position.y;}";
static const char fragment_shader[] =
    "precision highp float; varying vec3 n,p;varying vec2 uv;uniform vec3 tint,eye;uniform vec4 "
    "surface,uvbox;"
    "uniform int kind;uniform float shadow;uniform sampler2D tex;"
    "void main(){if(kind==-2){float "
    "d=length((uv-.5)*2.);gl_FragColor=vec4(.10,.11,.10,(1.-smoothstep(.13,.98,d))*.26*shadow);return;}"
    "if(kind==-1){gl_FragColor=texture2D(tex,uvbox.xy+vec2(uv.x,1.-uv.y)*uvbox.zw);return;}"
    "vec4 t=kind>0?texture2D(tex,uv):vec4(1.);if(t.a<.4)discard;"
    "vec3 "
    "base=tint*pow(t.rgb,vec3(2.2));if(surface.z>.5){gl_FragColor=vec4(pow(base,vec3(.45455)).bgr,1.);"
    "return;}"
    "vec3 N=normalize(n),L=normalize(vec3(-.42,.68,.74)),V=normalize(eye-p),H=normalize(L+V);"
    "float lam=max(dot(N,L),0.), spec=pow(max(dot(N,H),0.),mix(84.,9.,surface.y));"
    "vec3 refl=reflect(-V,N);float "
    "softbox=smoothstep(.3,.86,refl.y)*.36+smoothstep(.78,.99,-refl.x)*.36;"
    "vec3 lit=base*(.40+.48*lam+.13*N.y)+mix(vec3(.08),base,surface.x)*(.52*spec+.7*softbox);"
    "gl_FragColor=vec4(pow(clamp(lit,0.,1.),vec3(.45455)).bgr,1.);}";
static GLuint shader(GLenum type, const char *src) {
    GLuint id = glCreateShader(type);
    glShaderSource(id, 1, &src, NULL);
    glCompileShader(id);
    GLint ok;
    glGetShaderiv(id, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(id, sizeof log, NULL, log);
        fprintf(stderr, "B.A.P. 3D shader: %s\n", log);
        glDeleteShader(id);
        return 0;
    }
    return id;
}
static bool setup_program(void) {
    GLuint vs = shader(GL_VERTEX_SHADER, vertex_shader),
           fs = shader(GL_FRAGMENT_SHADER, fragment_shader);
    if (!vs || !fs)
        return false;
    program = glCreateProgram();
    glAttachShader(program, vs);
    glAttachShader(program, fs);
    glBindAttribLocation(program, 0, "aP");
    glBindAttribLocation(program, 1, "aN");
    glBindAttribLocation(program, 2, "aUV");
    glLinkProgram(program);
    glDeleteShader(vs);
    glDeleteShader(fs);
    GLint ok;
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    if (!ok)
        return false;
    glUseProgram(program);
    glUniform1i(glGetUniformLocation(program, "tex"), 0);
    vp = glGetUniformLocation(program, "vp");
    eye = glGetUniformLocation(program, "eye");
    kind = glGetUniformLocation(program, "kind");
    tint = glGetUniformLocation(program, "tint");
    surface = glGetUniformLocation(program, "surface");
    rot = glGetUniformLocation(program, "rotor");
    uvbox = glGetUniformLocation(program, "uvbox");
    shadow_strength = glGetUniformLocation(program, "shadow");
    return true;
}
static bool mipmaps;
static float anisotropy;
static void texture_filter(void) {
    if (mipmaps) {
        glGenerateMipmap(GL_TEXTURE_2D);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    } else
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    if (anisotropy > 1)
        glTexParameterf(GL_TEXTURE_2D, 0x84FE, anisotropy);
}
static bool read_model(void) {
    FILE *f = fopen("inspect.mesh", "rb");
    if (!f)
        return false;
    int32_t meta[4];
    char magic[4];
    void *data = NULL;
    bool ok = false;
    if (fread(magic, 4, 1, f) != 1 || memcmp(magic, "BAP3", 4) || fread(meta, sizeof meta, 1, f) != 1)
        goto end;
    vertices = meta[1];
    batch_count = meta[2];
    int nt = meta[3];
    if (meta[0] != 1 || vertices < 3 || vertices > 300000 || batch_count < 1 ||
        batch_count > MAX_BATCHES || nt < 1 || nt >= MAX_TEXTURES)
        goto end;
    if (fread(lcd, sizeof lcd, 1, f) != 1 ||
        fread(batches, sizeof(Batch), batch_count, f) != (size_t)batch_count)
        goto end;
    for (int i = 0; i < batch_count; i++) {
        Batch b = batches[i];
        if (b.first < 0 || b.count < 0 || b.count > vertices || b.first > vertices - b.count ||
            b.texture < -1 || b.texture > nt || b.lamp > 24 || b.rotor > 1)
            goto end;
    }
    size_t bytes = vertices * 8 * sizeof(float);
    data = malloc(bytes);
    if (!data || fread(data, bytes, 1, f) != 1)
        goto end;
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, bytes + 6 * 8 * sizeof(float), NULL, GL_STATIC_DRAW);
    glBufferSubData(GL_ARRAY_BUFFER, 0, bytes, data);
    free(data);
    data = NULL;
    float floor_vertices[48];
    const int corners[6] = {0, 1, 2, 2, 3, 0};
    for (int i = 0; i < 6; i++) {
        int c = corners[i];
        float u = c == 1 || c == 2, v = c >= 2, y = (v - .5f) * 905 * cosf(.226893f);
        float point[8] = {
            (u - .5f) * 680, y, -8 - (y + 320) * tanf(.226893f), 0, .22495f, .9744f, u, v};
        memcpy(floor_vertices + i * 8, point, sizeof point);
    }
    glBufferSubData(GL_ARRAY_BUFFER, bytes, sizeof floor_vertices, floor_vertices);
    for (int i = 1; i <= nt; i++) {
        int32_t wh[2];
        if (fread(wh, sizeof wh, 1, f) != 1 || wh[0] < 1 || wh[1] < 1 || wh[0] > 2048 || wh[1] > 2048)
            goto end;
        size_t size = (size_t)wh[0] * wh[1] * 4;
        data = malloc(size);
        if (!data || fread(data, size, 1, f) != 1)
            goto end;
        glGenTextures(1, textures + i);
        glBindTexture(GL_TEXTURE_2D, textures[i]);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, wh[0], wh[1], 0, GL_RGBA, GL_UNSIGNED_BYTE, data);
        texture_filter();
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        free(data);
        data = NULL;
    }
    ok = glGetError() == GL_NO_ERROR;
end:
    free(data);
    fclose(f);
    return ok;
}
static GLuint texture_id(SDL_Texture *tex) {
    if (!tex || SDL_GL_BindTexture(tex, NULL, NULL))
        return 0;
    GLint id = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &id);
    SDL_GL_UnbindTexture(tex);
    return (GLuint)id;
}
static bool init(SDL_Window *window, SDL_Renderer *renderer) {
    win = window;
    original = SDL_GL_GetCurrentContext();
    if (!original) {
        SDL_SetError("missing renderer GL context");
        return false;
    }
    SDL_RendererInfo ri;
    if (SDL_GetRendererInfo(renderer, &ri))
        return false;
    fprintf(stderr, "B.A.P. 2D renderer: %s\n", ri.name);
    if (strcmp(ri.name, "opengles2")) {
        SDL_SetError("3D requires SDL GLES2 renderer");
        return false;
    }
    panel =
        SDL_CreateTexture(renderer, SDL_PIXELFORMAT_BGRA32, SDL_TEXTUREACCESS_TARGET, WIDTH, HEIGHT);
    image =
        SDL_CreateTexture(renderer, SDL_PIXELFORMAT_BGRA32, SDL_TEXTUREACCESS_TARGET, WIDTH, HEIGHT);
    panel_id = texture_id(panel);
    image_id = texture_id(image);
    if (!panel_id || !image_id)
        return false;
    SDL_GL_SetAttribute(SDL_GL_SHARE_WITH_CURRENT_CONTEXT, 1);
    context = SDL_GL_CreateContext(win);
    SDL_GL_SetAttribute(SDL_GL_SHARE_WITH_CURRENT_CONTEXT, 0);
    if (!context)
        return false;
    fprintf(stderr, "B.A.P. 3D GPU: %s (%s)\n", glGetString(GL_RENDERER), glGetString(GL_VERSION));
    const char *extensions = (const char *)glGetString(GL_EXTENSIONS);
    mipmaps = strstr((const char *)glGetString(GL_VERSION), "OpenGL ES 3") ||
              strstr(extensions, "GL_OES_texture_npot");
    if (strstr(extensions, "GL_EXT_texture_filter_anisotropic")) {
        glGetFloatv(0x84FF, &anisotropy);
        anisotropy = fminf(8, anisotropy);
    }
    if (!glIsTexture(panel_id) || !glIsTexture(image_id) || !setup_program() || !read_model())
        return false;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, image_id, 0);
    glGenRenderbuffers(1, &depth);
    glBindRenderbuffer(GL_RENDERBUFFER, depth);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT16, WIDTH, HEIGHT);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, depth);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
        return false;
    if (strstr((const char *)glGetString(GL_VERSION), "OpenGL ES 3")) {
        StorageMS store = (StorageMS)SDL_GL_GetProcAddress("glRenderbufferStorageMultisample");
        resolve_ms = (Blit)SDL_GL_GetProcAddress("glBlitFramebuffer");
        GLint samples = 0;
        glGetIntegerv(0x8D57, &samples);
        if (store && resolve_ms && samples >= 4) {
            glGenFramebuffers(1, &ms_fbo);
            glBindFramebuffer(GL_FRAMEBUFFER, ms_fbo);
            glGenRenderbuffers(1, &ms_color);
            glBindRenderbuffer(GL_RENDERBUFFER, ms_color);
            store(GL_RENDERBUFFER, 4, 0x8058, WIDTH, HEIGHT); // RGBA8
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, ms_color);
            glGenRenderbuffers(1, &ms_depth);
            glBindRenderbuffer(GL_RENDERBUFFER, ms_depth);
            store(GL_RENDERBUFFER, 4, GL_DEPTH_COMPONENT16, WIDTH, HEIGHT);
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, ms_depth);
            if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
                glDeleteFramebuffers(1, &ms_fbo);
                ms_fbo = 0;
            }
        }
    }
    fprintf(stderr, "B.A.P. 3D: %d samples, %.0fx anisotropy, %d vertices\n", ms_fbo ? 4 : 1,
            anisotropy, vertices);
    SDL_SetTextureBlendMode(image, SDL_BLENDMODE_NONE);
    return SDL_GL_MakeCurrent(win, original) == 0;
}
void inspect_shutdown(void) {
    if (context) {
        SDL_GL_MakeCurrent(win, original);
        SDL_GL_DeleteContext(context);
        context = NULL;
    }
    if (image)
        SDL_DestroyTexture(image);
    if (panel)
        SDL_DestroyTexture(panel);
    image = panel = NULL;
}
static bool error(void) {
    fprintf(stderr, "B.A.P. 3D unavailable: %s\n", SDL_GetError());
    failed = true;
    phase = FLAT;
    inspect_shutdown();
    return false;
}
bool inspect_prepare(SDL_Window *window, SDL_Renderer *renderer) {
    if (failed) {
        phase = FLAT;
        return false;
    }
    if (!context && !init(window, renderer))
        return error();
    if (SDL_SetRenderTarget(renderer, panel))
        return error();
    return true;
}
static void advance(void) {
    if (phase == ORBIT)
        return;
    unsigned now = SDL_GetTicks();
    elapsed += last_frame ? fminf(50, now - last_frame) : 0;
    last_frame = now;
    float t = bound(elapsed / duration, 0, 1), v = t * t * (3 - 2 * t);
    pose = (Pose){mixf(from.yaw, to.yaw, v), mixf(from.pitch, to.pitch, v), mixf(from.up, to.up, v),
                  mixf(from.zoom, to.zoom, v)};
    if (t >= 1)
        phase = phase == RETURNING ? FLAT : ORBIT;
}
typedef struct {
    float x, y, z;
} V3;
static float dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static V3 cross(V3 a, V3 b) {
    return (V3){a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
static void camera_matrix(float m[16], V3 *where) {
    float sy = sinf(pose.yaw), cy = cosf(pose.yaw), sp = sinf(pose.pitch), cp = cosf(pose.pitch),
          su = sinf(pose.up), cu = cosf(pose.up);
    V3 d = {sy * cp, sp * cu - cy * cp * su, sp * su + cy * cp * cu}, right = {cy, sy * su, -sy * cu},
       up = cross(d, right);
    float tan_v = tanf(35.f * 3.14159265f / 360), tan_h = .75f * tan_v, fit = 0;
    for (int i = 0; i < 8; i++) {
        V3 c = {i & 1 ? 243 : -243, i & 2 ? 356 : -321, i & 4 ? 72 : -141.5f};
        fit = fmaxf(fit,
                    dot(c, d) + 1.08f * fmaxf(fabsf(dot(c, right)) / tan_h, fabsf(dot(c, up)) / tan_v));
    }
    float distance = mixf(320 / tan_v, fit, bound(pose.up / placed.up, 0, 1)) * pose.zoom;
    *where = (V3){d.x * distance, d.y * distance, d.z * distance};
    // Column-major projection * view, with the camera fixed on the device origin.
    // Tight clipping gives the 16-bit depth buffer enough precision to separate the
    // PCB print, metal lids and LED faces even when viewed at a grazing angle.
    const float near_z = fmaxf(1, distance - 520), far_z = distance + 680;
    const float a = -(far_z + near_z) / (far_z - near_z), b = -2 * far_z * near_z / (far_z - near_z);
    float matrix[16] = {right.x / tan_h,
                        up.x / tan_v,
                        a * d.x,
                        -d.x,
                        right.y / tan_h,
                        up.y / tan_v,
                        a * d.y,
                        -d.y,
                        right.z / tan_h,
                        up.z / tan_v,
                        a * d.z,
                        -d.z,
                        0,
                        0,
                        b - a * distance,
                        distance};
    memcpy(m, matrix, sizeof matrix);
}
bool inspect_present(SDL_Renderer *renderer, unsigned lamps, const int angles[2]) {
    SDL_RenderFlush(renderer);
    if (SDL_SetRenderTarget(renderer, NULL))
        return error();
    SDL_RenderFlush(renderer);
    glFinish();
    if (SDL_GL_MakeCurrent(win, context))
        return error();
    advance();
    // SDL supplies a fresh render-target image; filter its LCD for the oblique view.
    glBindTexture(GL_TEXTURE_2D, panel_id);
    texture_filter();
    glBindFramebuffer(GL_FRAMEBUFFER, ms_fbo ? ms_fbo : fbo);
    glViewport(0, 0, WIDTH, HEIGHT);
    glEnable(GL_DEPTH_TEST);
    // The shared SDL BGRA target stores the web backdrop #161719 in BGR order.
    glClearColor(25.0f / 255, 23.0f / 255, 22.0f / 255, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glUseProgram(program);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    for (int i = 0; i < 3; i++)
        glEnableVertexAttribArray(i);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 32, 0);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 32, (void *)12);
    glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, 32, (void *)24);
    float matrix[16];
    V3 e;
    camera_matrix(matrix, &e);
    glUniformMatrix4fv(vp, 1, GL_FALSE, matrix);
    glUniform3f(eye, e.x, e.y, e.z);
    glUniform4f(uvbox, lcd[0] / WIDTH, lcd[1] / HEIGHT, lcd[2] / WIDTH, lcd[3] / HEIGHT);
    glUniform4f(rot, 0, 0, 1, 0);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDepthMask(GL_FALSE);
    glUniform1i(kind, -2);
    glUniform1f(shadow_strength, fminf(1, pose.up));
    glDrawArrays(GL_TRIANGLES, vertices, 6);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
    for (int i = 0; i < batch_count; i++) {
        const Batch *b = &batches[i];
        float angle = b->rotor >= 0 ? -angles[b->rotor] * .0174532925f : 0;
        glUniform4f(rot, b->pivot[0], b->pivot[1], cosf(angle), sinf(angle));
        bool lit = b->lamp >= 0 && ((lamps >> b->lamp) & 1u);
        glUniform3f(tint, lit ? 1 : b->rgb[0], lit ? .22f : b->rgb[1], lit ? .09f : b->rgb[2]);
        glUniform4f(surface, b->metal, b->rough, lit ? 1 : b->unlit, 0);
        glUniform1i(kind, b->texture);
        glBindTexture(GL_TEXTURE_2D, b->texture == -1 ? panel_id : textures[b->texture]);
        glDrawArrays(GL_TRIANGLES, b->first, b->count);
    }
    if (ms_fbo) {
        glBindFramebuffer(0x8CA8, ms_fbo); // READ_FRAMEBUFFER
        glBindFramebuffer(0x8CA9, fbo);    // DRAW_FRAMEBUFFER
        resolve_ms(0, 0, WIDTH, HEIGHT, 0, 0, WIDTH, HEIGHT, GL_COLOR_BUFFER_BIT, GL_NEAREST);
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glFinish();
    if (SDL_GL_MakeCurrent(win, original))
        return error();
    SDL_RenderCopy(renderer, phase == FLAT ? panel : image, NULL, NULL);
    SDL_RenderPresent(renderer);
    return true;
}
