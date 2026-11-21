/* GLSL 1.20 brush shading. Original model, sky and water passes are independent. */
#include "SDL.h"
static struct {
    GLuint program;
    GLint boost, bright, alpha, fog;
    SDL_GLContext context;
    GLuint(APIENTRY *CreateShader)(GLenum);
    void(APIENTRY *ShaderSource)(GLuint, GLsizei, const char **, const GLint *);
    void(APIENTRY *CompileShader)(GLuint);
    void(APIENTRY *GetShaderiv)(GLuint, GLenum, GLint *);
    void(APIENTRY *GetShaderInfoLog)(GLuint, GLsizei, GLsizei *, char *);
    GLuint(APIENTRY *CreateProgram)(void);
    void(APIENTRY *AttachShader)(GLuint, GLuint);
    void(APIENTRY *LinkProgram)(GLuint);
    void(APIENTRY *GetProgramiv)(GLuint, GLenum, GLint *);
    void(APIENTRY *GetProgramInfoLog)(GLuint, GLsizei, GLsizei *, char *);
    void(APIENTRY *DeleteShader)(GLuint);
    GLboolean(APIENTRY *IsProgram)(GLuint);
    void(APIENTRY *UseProgram)(GLuint);
    GLint(APIENTRY *GetUniformLocation)(GLuint, const char *);
    void(APIENTRY *Uniform1i)(GLint, GLint);
    void(APIENTRY *Uniform1f)(GLint, GLfloat);
    void(APIENTRY *Uniform4f)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
} mq_gl;
unsigned long long mq_shader_batches;

static GLuint mq_compile(GLenum kind, const char *source)
{
    GLuint shader = mq_gl.CreateShader(kind);
    mq_gl.ShaderSource(shader, 1, &source, NULL);
    mq_gl.CompileShader(shader);
    GLint ok = 0;
    mq_gl.GetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char message[1024] = {0};
        mq_gl.GetShaderInfoLog(shader, sizeof message, NULL, message);
        Sys_Error("Mojo Quake shader: %s", message);
    }
    return shader;
}
static void mq_use_lightmap(qboolean bright, float boost, float alpha)
{
    SDL_GLContext ctx = SDL_GL_GetCurrentContext();
    if (!mq_gl.program || mq_gl.context != ctx || !mq_gl.IsProgram(mq_gl.program)) {
#define MQ_RESOLVE(fn)                                                                                 \
    do {                                                                                               \
        mq_gl.fn = (__typeof__(mq_gl.fn))SDL_GL_GetProcAddress("gl" #fn);                              \
        if (!mq_gl.fn)                                                                                 \
            Sys_Error("OpenGL entry gl" #fn " unavailable");                                           \
    } while (0)
        MQ_RESOLVE(CreateShader);
        MQ_RESOLVE(ShaderSource);
        MQ_RESOLVE(CompileShader);
        MQ_RESOLVE(GetShaderiv);
        MQ_RESOLVE(GetShaderInfoLog);
        MQ_RESOLVE(CreateProgram);
        MQ_RESOLVE(AttachShader);
        MQ_RESOLVE(LinkProgram);
        MQ_RESOLVE(GetProgramiv);
        MQ_RESOLVE(GetProgramInfoLog);
        MQ_RESOLVE(DeleteShader);
        MQ_RESOLVE(UseProgram);
        MQ_RESOLVE(IsProgram);
        MQ_RESOLVE(GetUniformLocation);
        MQ_RESOLVE(Uniform1i);
        MQ_RESOLVE(Uniform1f);
        MQ_RESOLVE(Uniform4f);
#undef MQ_RESOLVE
        const char *vs =
            "#version 120\nvarying vec2 uv,lm; varying float distanceToEye;"
            "void main(){gl_Position=ftransform();uv=gl_MultiTexCoord0.xy;lm=gl_MultiTexCoord1.xy;"
            "distanceToEye=abs((gl_ModelViewMatrix*gl_Vertex).z);}";
        const char *fs =
            "#version 120\nuniform sampler2D surface,illumination,emissive;"
            "uniform float boost,alpha;uniform int bright;uniform vec4 fog;"
            "varying vec2 uv,lm;varying float distanceToEye;"
            "void main(){vec4 t=texture2D(surface,uv);vec3 "
            "c=min(vec3(1.),t.rgb*texture2D(illumination,lm).rgb*boost);"
            "if(bright!=0){vec4 e=texture2D(emissive,uv);c=mix(c,e.rgb,e.a);}"
            "float d=fog.a*distanceToEye;gl_FragColor=vec4(mix(fog.rgb,c,exp(-d*d)),t.a*alpha);}";
        GLuint v = mq_compile(GL_VERTEX_SHADER, vs), f = mq_compile(GL_FRAGMENT_SHADER, fs);
        GLuint id = mq_gl.CreateProgram();
        mq_gl.AttachShader(id, v);
        mq_gl.AttachShader(id, f);
        mq_gl.LinkProgram(id);
        GLint ok = 0;
        mq_gl.GetProgramiv(id, GL_LINK_STATUS, &ok);
        if (!ok) {
            char log[1024] = {0};
            mq_gl.GetProgramInfoLog(id, sizeof log, NULL, log);
            Sys_Error("Quake program: %s", log);
        }
        mq_gl.DeleteShader(v);
        mq_gl.DeleteShader(f);
        mq_gl.UseProgram(id);
        mq_gl.Uniform1i(mq_gl.GetUniformLocation(id, "surface"), 0);
        mq_gl.Uniform1i(mq_gl.GetUniformLocation(id, "illumination"), 1);
        mq_gl.Uniform1i(mq_gl.GetUniformLocation(id, "emissive"), 2);
        mq_gl.boost = mq_gl.GetUniformLocation(id, "boost");
        mq_gl.alpha = mq_gl.GetUniformLocation(id, "alpha");
        mq_gl.bright = mq_gl.GetUniformLocation(id, "bright");
        mq_gl.fog = mq_gl.GetUniformLocation(id, "fog");
        mq_gl.context = ctx;
        mq_gl.program = id;
        Con_Printf("Mojo Quake GLSL brush shader ready\n");
    }
    const float *color = Fog_GetColor();
    mq_gl.UseProgram(mq_gl.program);
    mq_gl.Uniform1i(mq_gl.bright, bright);
    mq_gl.Uniform1f(mq_gl.alpha, alpha);
    mq_gl.Uniform1f(mq_gl.boost, boost);
    mq_gl.Uniform4f(mq_gl.fog, color[0], color[1], color[2], Fog_GetDensity() / 64.0f);
    ++mq_shader_batches;
}
