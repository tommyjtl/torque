/* Storage, validation of the supported IWAD/index pair and GL submission.
 * Asset decoding and all game rules reside in classic.mojo.
 */
static unsigned char *classic_wad, *classic_index;
static uint32_t *classic_texels;
static int32_t *classic_bases, *sound_sectors;
void *cl_sound_sectors(void) { return sound_sectors; }
static GLuint *classic_textures;
static Vertex triangle_batch[768];
static int batch_count, batch_mat = -1, batch_style;
static int32_t columns[320];
void *cl_sky_columns(void) { return columns; }
void *cl_wad(void) { return classic_wad ? classic_wad : (void *)pixels; }
void *cl_ix(void) { return classic_index ? classic_index : (void *)pixels; }
void *cl_texels(void) { return classic_texels ? classic_texels : pixels; }
void *cl_bases(void) { return classic_bases; }
int cl_upload(int id, int width, int height, uint32_t *data) {
    if (classic_textures[id])
        gDeleteTextures(1, &classic_textures[id]);
    classic_textures[id] = texture(width, height, data, 1);
    return 0;
}
int cl_flush(void) {
    if (batch_count) {
        gUniform1i(style_loc, batch_style);
        if (batch_style >= 2) {
            gEnable(GL_BLEND);
            gBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        }
        gBindTexture(GL_TEXTURE_2D, classic_textures[batch_mat]);
        gBufferData(GL_ARRAY_BUFFER, batch_count * sizeof(Vertex), triangle_batch, GL_STREAM_DRAW);
        gDrawArrays(GL_TRIANGLES, 0, batch_count);
        if (batch_style >= 2)
            gDisable(GL_BLEND);
        batch_count = 0;
    }
    return 0;
}
int cl_vertex(int id, int style, float x, float y, float z, float u, float v) {
    if (id != batch_mat || style != batch_style || batch_count == 768) {
        cl_flush();
        batch_mat = id;
        batch_style = style;
    }
    triangle_batch[batch_count++] = (Vertex){x, y, z, u, v};
    return 0;
}
static int32_t voices[49], music_state[160];
static float music_buffer[512];
void *cl_music_buffer(void) { return music_buffer; }
static float music_synth[18 * 14], music_wave[2048];
void *cl_music_state(void) { return music_state; }
void *cl_music_synth(void) { return music_synth; }
void *cl_music_wave(void) { return music_wave; }
static unsigned counts[4];
int32_t *cl_voices(void) { return voices; }
int cl_need_audio(int target) {
    if (!speaker)
        return 0;
    unsigned queued = api_GetQueuedAudioSize(speaker);
    static int saw_nonempty;
    if (queued)
        saw_nonempty = 1;
    else if (saw_nonempty) {
        ++empty_audio_queue_events;
        saw_nonempty = 0;
    }
    return queued < (size_t)target * 2 * sizeof(float);
}
int cl_sound_event(int kind) {
    if (kind >= 10 && kind < 14)
        counts[kind - 10]++;
    return 0;
}
static unsigned char *read_verified(const char *path, size_t n, const char *hex) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        perror(path);
        return NULL;
    }
    unsigned char *p = malloc(n);
    int ok = p && fread(p, 1, n, f) == n && fgetc(f) == EOF;
    fclose(f);
    if (!ok) {
        free(p);
        fprintf(stderr, "Unexpected asset size: %s\n", path);
        return NULL;
    }
    unsigned char digest[32];
#ifdef __APPLE__
    CC_SHA256(p, (CC_LONG)n, digest);
#else
    void *crypto = dlopen("libcrypto.so.3", RTLD_NOW | RTLD_LOCAL);
    unsigned char *(*sha)(const unsigned char *, size_t, unsigned char *) =
        crypto ? dlsym(crypto, "SHA256") : NULL;
    if (!sha || !sha(p, n, digest)) {
        fprintf(stderr, "Could not verify IWAD using libcrypto.so.3\n");
        free(p);
        if (crypto)
            dlclose(crypto);
        return NULL;
    }
    dlclose(crypto);
#endif
    char result[65];
    for (int i = 0; i < 32; i++)
        snprintf(result + i * 2, 3, "%02x", digest[i]);
    if (strcmp(result, hex)) {
        fprintf(stderr, "Unsupported IWAD or layout index: %s\n", path);
        free(p);
        return NULL;
    }
    return p;
}
typedef struct {
    const char *map;
    size_t bytes;
    int words, sectors, sprites;
    const char *digest;
} MapInfo;
static const MapInfo campaign_catalog[] = {
#include "campaign_indexes.inc"
};
static int32_t *map_layout;
void *cl_layout(void) { return map_layout ? map_layout : (void *)pixels; }
int cl_saved_sectors(int map) { return campaign_catalog[map - 1].sectors; }
// Versions 2 and 3 used the same actor IDs before blur spheres were indexed.
static const int v3_sprites[] = {115, 241, 366, 240, 257, 446, 335, 111, 221};

int cl_legacy_available(void) {
    return access(legacy_path, R_OK) == 0 && access(save_path, F_OK) != 0;
}
int cl_read_legacy(int32_t *out) {
    struct stat old_slot, new_slot;
    if (stat(legacy_path, &old_slot) == 0 && stat(save_path, &new_slot) == 0 &&
        old_slot.st_dev == new_slot.st_dev && old_slot.st_ino == new_slot.st_ino) {
        fprintf(stderr, "Choose a separate campaign save slot for this import.\n");
        return 0;
    }
    uint32_t buf[100];
    FILE *f = fopen(legacy_path, "rb");
    if (!f)
        return 0;
    int ok = fread(buf, sizeof buf, 1, f) == 1 && fgetc(f) == EOF;
    fclose(f);
    if (!ok || buf[0] != 0x31595753 || buf[1] != 1 || buf[2] != wad_hash ||
        buf[99] != hash(buf, 99 * 4))
        return 0;
    memcpy(out, buf + 3, 96 * 4);
    return 1;
}

int cl_read_save(int32_t *out) {
    FILE *f = NULL;
    uint32_t *buf = save_buffer;
    if (check_memory) {
        if (!saved)
            return 0;
        buf = memory_save;
    } else {
        f = fopen(save_path, "rb");
        if (!f)
            return 0;
        if (fread(buf, 4, 3, f) != 3) {
            fclose(f);
            return 0;
        }
    }
    int map = buf[1] >> 8;
    int version = buf[1] & 255;
    if (buf[0] != 0x31595753 || (version < 2 || version > 4) || buf[2] != wad_hash || map < 1 ||
        map > 9) {
        if (f)
            fclose(f);
        return 0;
    }
    const MapInfo *level = &campaign_catalog[map-1];
    size_t sprites = version < 4 ? v3_sprites[map-1] : level->sprites;
    size_t added = 16 * (level->sprites - sprites);
    size_t words = level->words - added - (version == 2 ? 32 : 0);
    if (f) {
        int ok = fread(buf + 3, 4, words + 1, f) == words + 1 && fgetc(f) == EOF;
        fclose(f);
        if (!ok)
            return 0;
    }
    if (buf[3 + words] != hash(buf, 4 * (words + 3)))
        return 0;
    size_t player = 11 + level->sectors;
    size_t prefix = player + (version == 2 ? 16 : 48);
    memcpy(out, buf + 3, prefix * sizeof *out);
    if (version == 2) {
        memset(out + prefix, 0, 32 * sizeof *out);
        out[player+11] = 3;
        out[player+12] = 1;
    }
    size_t actor_base = player + 48;
    size_t actor_words = 16 * sprites;
    memcpy(out + actor_base, buf + 3 + prefix, actor_words * sizeof *out);
    memset(out + actor_base + actor_words, 0, added * sizeof *out);
    memcpy(out + actor_base + actor_words + added, buf + 3 + prefix + actor_words,
           (words - prefix - actor_words) * sizeof *out);
    // Mojo initializes the appended actors after loading the destination map.
    return (int)(sprites << 8) | map;
}

static char first_index[4096];
static int state_capacity;

int cl_change_map(int map) {
    if (map < 1 || map > 9)
        return 0;
    if (campaign_map == map)
        return 1;
    const char *index = first_index;
    char path[4096];
    if (map != 1) {
        const char *ext = strrchr(index, '.');
        if (!ext || snprintf(path, sizeof path, "%.*s.e%dm%d.syi", (int)(ext - index), index,
                             1 + (map - 1) / 9, 1 + (map - 1) % 9) >= (int)sizeof path)
            return 0;
        index = path;
    }
    unsigned char *candidate =
        read_verified(index, campaign_catalog[map - 1].bytes, campaign_catalog[map - 1].digest);
    if (!candidate)
        return 0;
    const int32_t *ix = (const int32_t *)candidate;
    size_t texels = 0;
    for (int i = 0; i < ix[9]; ++i)
        texels += (size_t)ix[46 + 5 * i] * ix[47 + 5 * i];
    int32_t *heard = calloc(ix[20] / 26, sizeof *heard);
    int32_t *bases = calloc(ix[9], sizeof *bases);
    GLuint *textures_for_map = calloc(ix[9] * 4, sizeof *textures_for_map);
    uint32_t *decoded = calloc(texels * 4, sizeof *decoded);
    if (!heard || !bases || !textures_for_map || !decoded) {
        free(heard);
        free(bases);
        free(textures_for_map);
        free(decoded);
        free(candidate);
        return 0;
    }
    if (context && classic_index)
        gDeleteTextures(((const int32_t *)classic_index)[9] * 4, classic_textures);
    free(sound_sectors);
    free(classic_bases);
    free(classic_textures);
    free(classic_texels);
    free(classic_index);
    batch_count = 0;
    memset(voices, 0, sizeof voices);
    sound_sectors = heard;
    classic_bases = bases;
    classic_textures = textures_for_map;
    classic_texels = decoded;
    classic_index = candidate;
    campaign_map = map;
    map_layout = (int32_t *)(candidate + campaign_catalog[map - 1].bytes) - 10;
    payload_words = campaign_catalog[map - 1].words;
    return 1;
}

static int prepare_classic(const char *wad, const char *index, int map) {
    classic_wad = read_verified(wad, 4196020,
                                "1d7d43be501e67d927e415e0b8f3e29c3bf33075e859721816f652a526cac771");
    if (!classic_wad)
        return 0;
    if (!realpath(index, first_index)) {
        perror(index);
        return 0;
    }
    for (int i = 0; i < 9; ++i)
        if (campaign_catalog[i].words > state_capacity)
            state_capacity = campaign_catalog[i].words;
    return cl_change_map(map);
}
