/* Storage, validation of the supported IWAD/index pair and GL submission.
 * Asset decoding and all game rules reside in classic.mojo.
 */
static unsigned char *classic_wad, *classic_index;
static uint32_t *classic_texels;
static int32_t classic_bases[100];
static GLuint classic_textures[100 * 4];
static Vertex triangle_batch[768];
static int batch_count, batch_mat = -1;
void *cl_wad(void) { return classic_wad ? classic_wad : (void *)pixels; }
void *cl_ix(void) { return classic_index ? classic_index : (void *)pixels; }
void *cl_texels(void) { return classic_texels ? classic_texels : pixels; }
void *cl_bases(void) { return classic_bases; }
int cl_upload(int id, int width, int height, uint32_t *data) {
    classic_textures[id] = texture(width, height, data, 1);
    return 0;
}
int cl_flush(void) {
    if (batch_count) {
        gBindTexture(GL_TEXTURE_2D, classic_textures[batch_mat]);
        gBufferData(GL_ARRAY_BUFFER, batch_count * sizeof(Vertex), triangle_batch,
                    GL_STREAM_DRAW);
        gDrawArrays(GL_TRIANGLES, 0, batch_count);
        batch_count = 0;
    }
    return 0;
}
int cl_vertex(int id, float x, float y, float z, float u, float v) {
    if (id != batch_mat || batch_count == 768) {
        cl_flush();
        batch_mat = id;
    }
    triangle_batch[batch_count++] = (Vertex){x, y, z, u, v};
    return 0;
}
static int32_t voices[17];
static unsigned counts[4];
int32_t *cl_voices(void) { return voices; }
int cl_need_audio(void) {
    return speaker && api_GetQueuedAudioSize(speaker) < 1536 * sizeof(float);
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
static int prepare_classic(const char *wad, const char *index) {
    classic_wad = read_verified(
        wad, 4196020, "1d7d43be501e67d927e415e0b8f3e29c3bf33075e859721816f652a526cac771");
    classic_index = read_verified(
        index, 157700, "2f4dc8d604a7d146f3a8388b2235f73746876faae2338441fe59728b7cdc1343");
    classic_texels = calloc(508441 * 4, sizeof *classic_texels);
    return classic_wad && classic_index && classic_texels;
}
