/* One length-delimited game framebuffer on the controller's stdout pipe.
 * Ordinary screenshots and desktop play never enter this path. */
static void mq_write_agent_frame(void)
{
    extern int mq_agent_tick;
#ifdef GLQUAKE
    const size_t length = (size_t)glwidth * glheight * 3;
    byte *pixels = malloc(length);
    if (!pixels)
        Sys_Error("Cannot allocate agent frame");
    GLint alignment;
    glGetIntegerv(GL_PACK_ALIGNMENT, &alignment);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(glx, gly, glwidth, glheight, GL_RGB, GL_UNSIGNED_BYTE, pixels);
    glPixelStorei(GL_PACK_ALIGNMENT, alignment);
    printf("MQ_FRAME %d %d %d RGB_BOTTOM_UP\n", mq_agent_tick, glwidth, glheight);
    fwrite(pixels, 1, length, stdout);
    free(pixels);
#else
    extern const byte *mq_display_palette(void);
    D_EnableBackBufferAccess();
    printf("MQ_FRAME %d %d %d INDEXED\n", mq_agent_tick, vid.width, vid.height);
    fwrite(mq_display_palette(), 1, 768, stdout);
    for (int y = 0; y < vid.height; ++y)
        fwrite(vid.buffer + y * vid.rowbytes, 1, vid.width, stdout);
    D_DisableBackBufferAccess();
#endif
    if (fflush(stdout) || ferror(stdout))
        Sys_Error("Lost agent frame connection");
}
