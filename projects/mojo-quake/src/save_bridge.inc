/* Native storage and live-engine adapters for the Mojo snapshot codec. */
#include <ctype.h>
#include <math.h>
#include <stddef.h>
#include <unistd.h>

enum { MQ_META, MQ_GLOBALS, MQ_ENTITY, MQ_FIELDS, MQ_STRING, MQ_STYLE };
enum { MQ_MAX_SAVE = 16 * 1024 * 1024 };
extern int mq_snapshot(byte *, int, int *, int);
extern uint32_t mq_hash(const byte *, int, uint32_t);
extern uint32_t mq_server_seed;
extern char pr_string_temp[128];
extern int mq_string_count(void);
extern void mq_define_string(int index, const char *value);

typedef struct {
    char map[64];
    uint32_t map_hash, code_hash, seed;
    int32_t globals, fields, entities, strings, stride, field_offset;
    int32_t skill, runes, lastcheck, checkleaf, name_string, temp_string;
    float gravity, angles[3], spawn[NUM_SPAWN_PARMS];
    double time, lastchecktime;
} mq_meta_t;

typedef struct {
    int32_t free, alpha, rank;
    float freetime;
} mq_entity_t;

_Static_assert(sizeof(mq_entity_t) == 16 && MAX_LIGHTSTYLES == 64, "snapshot ABI");
_Static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "snapshot word order");
static mq_meta_t mq_meta;
static mq_entity_t mq_entity;
static int mq_rank[MAX_EDICTS], mq_load_hold;
static byte *mq_pending;
static int mq_pending_size;

static qboolean mq_asset(const char *path, uint32_t *hash, void *header, size_t header_size)
{
    FILE *file = NULL;
    int left = COM_FOpenFile(path, &file);
    if (!file || left < (int)header_size) {
        if (file)
            fclose(file);
        return false;
    }
    byte bytes[16384];
    uint32_t sum = 2166136261u;
    while (left > 0) {
        int n = left < (int)sizeof bytes ? left : (int)sizeof bytes;
        if (fread(bytes, 1, n, file) != (size_t)n) {
            fclose(file);
            return false;
        }
        if (header_size) {
            memcpy(header, bytes, header_size);
            header_size = 0;
        }
        sum = mq_hash(bytes, n, sum);
        left -= n;
    }
    fclose(file);
    *hash = sum;
    return true;
}

static qboolean mq_map_path(const char *name, char *path)
{
    size_t length = strnlen(name, sizeof mq_meta.map);
    if (!length || length >= MAX_QPATH - 10)
        return false;
    for (size_t i = 0; i < length; ++i)
        if (!isalnum((unsigned char)name[i]) && name[i] != '_')
            return false;
    snprintf(path, MAX_QPATH, "maps/%s.bsp", name);
    return true;
}

extern void mq_capture_links(int *codes);
extern int mq_link_code_valid(int code, int count);
extern void mq_restore_link(edict_t *e, int code);

static void mq_layout(int layout[5])
{
    layout[0] = sizeof mq_meta;
    layout[1] = mq_meta.globals;
    layout[2] = mq_meta.fields;
    layout[3] = mq_meta.entities;
    layout[4] = mq_meta.strings;
}

static qboolean mq_capture_header(void)
{
    char path[MAX_QPATH];
    mq_capture_links(mq_rank);
    memset(&mq_meta, 0, sizeof mq_meta);
    qstrncpy(mq_meta.map, sv.name, sizeof mq_meta.map);
    if (!mq_map_path(sv.name, path) || !mq_asset(path, &mq_meta.map_hash, NULL, 0) ||
        !mq_asset("progs.dat", &mq_meta.code_hash, NULL, 0))
        return false;
    mq_meta.skill = current_skill;
    mq_meta.runes = svs.serverflags;
    mq_meta.seed = mq_server_seed;
    mq_meta.time = sv.time;
    mq_meta.lastcheck = sv.lastcheck;
    mq_meta.lastchecktime = sv.lastchecktime;
    mq_meta.checkleaf = sv.checkleaf ? (int)(sv.checkleaf - sv.worldmodel->leafs) : -1;
    mq_meta.gravity = sv_gravity.value;
    mq_meta.globals = progs->numglobals;
    mq_meta.fields = progs->entityfields;
    mq_meta.entities = sv.num_edicts;
    mq_meta.strings = mq_string_count();
    mq_meta.stride = pr_edict_size;
    mq_meta.field_offset = offsetof(edict_t, v);
    for (int i = 0; i < mq_meta.strings; ++i) {
        const char *s = PR_GetString(-1 - i);
        if (s == svs.clients[0].name)
            mq_meta.name_string = -1 - i;
        if (s == pr_string_temp)
            mq_meta.temp_string = -1 - i;
    }
    memcpy(mq_meta.angles, cl.viewangles, sizeof mq_meta.angles);
    memcpy(mq_meta.spawn, svs.clients[0].spawn_parms, sizeof mq_meta.spawn);
    return true;
}

const void *mq_snapshot_source(int kind, int i, int *size)
{
    const void *data = NULL;
    const char *s = NULL;
    switch (kind) {
    case MQ_META:
        data = &mq_meta;
        *size = sizeof mq_meta;
        break;
    case MQ_GLOBALS:
        data = pr_globals;
        *size = 4 * mq_meta.globals;
        break;
    case MQ_ENTITY: {
        edict_t *e = EDICT_NUM(i);
        mq_entity = (mq_entity_t){e->free, e->alpha, mq_rank[i], e->freetime};
        data = &mq_entity;
        *size = sizeof mq_entity;
        break;
    }
    case MQ_FIELDS:
        data = &EDICT_NUM(i)->v;
        *size = 4 * mq_meta.fields;
        break;
    case MQ_STRING:
        s = PR_GetString(-1 - i);
        break;
    case MQ_STYLE:
        s = sv.lightstyles[i];
        *size = 0;
        break;
    }
    if (s) {
        data = s;
        *size = (int)strlen(s) + 1;
    }
    return data;
}

static qboolean mq_header_matches(void)
{
    char path[MAX_QPATH];
    dprograms_t program;
    dheader_t map;
    uint32_t code_hash, map_hash;
    if (!mq_map_path(mq_meta.map, path) || !mq_asset(path, &map_hash, &map, sizeof map) ||
        !mq_asset("progs.dat", &code_hash, &program, sizeof program))
        return false;
    return map_hash == mq_meta.map_hash && code_hash == mq_meta.code_hash &&
           mq_meta.fields == program.entityfields && mq_meta.globals == program.numglobals &&
           mq_meta.stride == 4 * mq_meta.fields + sizeof(edict_t) - sizeof(entvars_t) &&
           mq_meta.field_offset == offsetof(edict_t, v) && mq_meta.checkleaf >= -1 &&
           mq_meta.checkleaf < map.lumps[LUMP_LEAFS].filelen / (int)sizeof(bsp29_dleaf_t) &&
           mq_meta.lastcheck >= 0 && mq_meta.lastcheck <= 1 && mq_meta.skill >= 0 &&
           mq_meta.skill <= 3 && isfinite(mq_meta.gravity) && isfinite(mq_meta.time) &&
           mq_meta.time >= 0;
}

static char *mq_clone(const byte *data, int size)
{
    char *s = Hunk_AllocName(size, "saved string");
    memcpy(s, data, size);
    return s;
}

int mq_snapshot_receive(int mode, int kind, int i, const byte *data, int size, int *layout)
{
    const qboolean apply = mode == 2;
    switch (kind) {
    case MQ_META:
        memcpy(&mq_meta, data, sizeof mq_meta);
        mq_layout(layout);
        if (!apply)
            return mq_header_matches();
        break;
    case MQ_GLOBALS:
        if (apply)
            memcpy(pr_globals, data, size);
        break;
    case MQ_ENTITY:
        memcpy(&mq_entity, data, sizeof mq_entity);
        if ((unsigned)mq_entity.free > 1 || (unsigned)mq_entity.alpha > 255 ||
            !mq_link_code_valid(mq_entity.rank, mq_meta.entities))
            return 0;
        if (apply) {
            edict_t *e = EDICT_NUM(i);
            e->free = mq_entity.free;
            e->alpha = mq_entity.alpha;
            e->freetime = mq_entity.freetime;
            mq_rank[i] = mq_entity.rank;
        }
        break;
    case MQ_FIELDS:
        if (apply)
            memcpy(&EDICT_NUM(i)->v, data, size);
        break;
    case MQ_STRING:
        if (apply) {
            const char *old = i < mq_string_count() ? PR_GetString(-1 - i) : NULL;
            const char *s = (const char *)data;
            if (-1 - i == mq_meta.temp_string) {
                qstrncpy(pr_string_temp, s, sizeof pr_string_temp);
                s = pr_string_temp;
            } else if (-1 - i == mq_meta.name_string) {
                qstrncpy(svs.clients[0].name, s, sizeof svs.clients[0].name);
                s = svs.clients[0].name;
            } else if (old && !strcmp(old, s))
                s = old;
            else
                s = mq_clone(data, size);
            mq_define_string(i, s);
        }
        break;
    case MQ_STYLE:
        if (apply)
            sv.lightstyles[i] = size ? mq_clone(data, size) : NULL;
        break;
    }
    return 1;
}

static int mq_link_order(const void *a, const void *b)
{
    int x = *(const int *)a, y = *(const int *)b;
    return mq_rank[x] == mq_rank[y] ? x - y : mq_rank[x] - mq_rank[y];
}

static void mq_apply_snapshot(void)
{
    int layout[] = {sizeof mq_meta, 0, 0, 0, 0};
    static int ids[MAX_EDICTS];
    for (int i = 0; i < sv.num_edicts; ++i)
        SV_UnlinkEdict(EDICT_NUM(i));
    sv.num_edicts = mq_meta.entities;
    if (!mq_snapshot(mq_pending, mq_pending_size, layout, 2))
        Host_Error("Snapshot changed during restore");
    for (int i = 0; i < sv.num_edicts; ++i)
        ids[i] = i;
    qsort(ids, sv.num_edicts, sizeof *ids, mq_link_order);
    for (int j = 0; j < sv.num_edicts; ++j) {
        edict_t *e = EDICT_NUM(ids[j]);
        mq_restore_link(e, mq_rank[ids[j]]);
    }
    sv.time = mq_meta.time;
    sv.lastcheck = mq_meta.lastcheck;
    sv.lastchecktime = mq_meta.lastchecktime;
    sv.checkleaf = mq_meta.checkleaf < 0 ? NULL : &sv.worldmodel->leafs[mq_meta.checkleaf];
    svs.serverflags = mq_meta.runes;
    mq_server_seed = mq_meta.seed;
    Cvar_SetValue("sv_gravity", mq_meta.gravity);
    memcpy(svs.clients[0].spawn_parms, mq_meta.spawn, sizeof mq_meta.spawn);
    memcpy(cl.viewangles, mq_meta.angles, sizeof mq_meta.angles);
}

void mq_before_player_move(void)
{
    if (!mq_load_hold)
        return;
    mq_apply_snapshot();
    free(mq_pending);
    mq_pending = NULL;
    mq_load_hold = 0;
    sv.paused = false;
}

uint32_t mq_exact_digest(void)
{
    if (!mq_capture_header())
        return 0;
    int layout[5];
    mq_layout(layout);
    byte *bytes = malloc(MQ_MAX_SAVE);
    if (!bytes)
        return 0;
    int n = mq_snapshot(bytes, MQ_MAX_SAVE, layout, 0);
    uint32_t checksum = n > 0 ? mq_hash(bytes, n, 2166136261u) : 0;
    free(bytes);
    return checksum;
}

static qboolean mq_save_slot(const char *name, const char *comment)
{
    if (!mq_capture_header())
        return false;
    int layout[5];
    mq_layout(layout);
    byte *bytes = malloc(MQ_MAX_SAVE);
    if (!bytes)
        return false;
    int size = mq_snapshot(bytes, MQ_MAX_SAVE, layout, 0);
    char tmp[MAX_OSPATH + 16];
    snprintf(tmp, sizeof tmp, "%s.tmp.XXXXXX", name);
    int fd = size > 0 ? mkstemp(tmp) : -1;
    FILE *f = fd >= 0 ? fdopen(fd, "wb") : NULL;
    qboolean ok = false;
    if (f) {
        ok = fprintf(f, "6\n%s\n", comment) > 0 && fwrite(bytes, 1, size, f) == (size_t)size &&
             fflush(f) == 0 && fsync(fd) == 0;
        if (fclose(f))
            ok = false;
        if (ok)
            ok = rename(tmp, name) == 0;
    } else if (fd >= 0)
        close(fd);
    if (!ok && fd >= 0)
        unlink(tmp);
    free(bytes);
    return ok;
}

static qboolean mq_load_slot(FILE *file)
{
    // The version line has already been consumed. Keep all bytes private until
    // the entire snapshot, map and bytecode identities have passed validation.
    char comment[128];
    if (!fgets(comment, sizeof comment, file))
        return false;
    long start = ftell(file);
    if (start < 0 || fseek(file, 0, SEEK_END))
        return false;
    long bytes = ftell(file) - start;
    if (bytes <= 0 || bytes > MQ_MAX_SAVE || fseek(file, start, SEEK_SET))
        return false;
    byte *buffer = malloc(bytes);
    int layout[] = {sizeof mq_meta, 0, 0, 0, 0};
    mq_meta_t prior = mq_meta;
    if (!buffer || fread(buffer, 1, bytes, file) != (size_t)bytes ||
        !mq_snapshot(buffer, bytes, layout, 1)) {
        mq_meta = prior;
        free(buffer);
        return false;
    }
    char map[MAX_QPATH];
    qstrncpy(map, mq_meta.map, sizeof map);
    CL_Disconnect_f();
    current_skill = mq_meta.skill;
    Cvar_SetValue("skill", current_skill);
    SV_SpawnServer(map);
    if (!sv.active) {
        free(buffer);
        return false;
    }
    free(mq_pending);
    mq_pending = buffer;
    mq_pending_size = bytes;
    mq_load_hold = 1;
    mq_apply_snapshot();
    sv.paused = true;
    sv.loadgame = true;
    CL_EstablishConnection("local");
    Host_Reconnect_f();
    return true;
}

int mq_restore_in_progress(void) { return mq_load_hold; }

void mq_cancel_restore(void)
{
    free(mq_pending);
    mq_pending = NULL;
    mq_load_hold = 0;
}
