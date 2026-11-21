extern void mq_draw_span(byte *, const byte *, int, int, float, float, float, float, float, float, int,
                         int, int, int);
static unsigned long long mq_wall_pixels;
void D_DrawSpans8(espan_t *span)
{
    for (; span; span = span->pnext) {
        float x = span->u, y = span->v;
        byte *dst = (byte *)d_viewbuffer + screenwidth * span->v + span->u;
        mq_draw_span(dst, cacheblock, cachewidth, span->count,
                     d_sdivzorigin + y * d_sdivzstepv + x * d_sdivzstepu,
                     d_tdivzorigin + y * d_tdivzstepv + x * d_tdivzstepu,
                     d_ziorigin + y * d_zistepv + x * d_zistepu, d_sdivzstepu, d_tdivzstepu, d_zistepu,
                     sadjust, tadjust, bbextents, bbextentt);
        mq_wall_pixels += span->count;
    }
}
unsigned long long mq_opaque_pixels(void) { return mq_wall_pixels; }
