extern void mq_mix8(int *, const byte *, const int *, const int *, const byte *, int, int);
extern void mq_mix16(int *, const int16_t *, int, int, const byte *, int, int);
unsigned long long mq_mixed_samples;
static void SND_PaintChannelFrom8_Generic(channel_t *ch, sfxcache_t *sound, int count, int start)
{
    ch->leftvol = qmin(255, ch->leftvol);
    ch->rightvol = qmin(255, ch->rightvol);
    mq_mix8(&paintbuffer[start].left, (const byte *)sound->data + ch->pos,
            snd_scaletable[ch->leftvol >> 3], snd_scaletable[ch->rightvol >> 3], snd_ramp, count,
            ch->kill);
    ch->pos += count;
    ch->kill = qmax(0, ch->kill - count);
    mq_mixed_samples += count;
}
static void SND_PaintChannelFrom16(channel_t *ch, sfxcache_t *sound, int count, int start)
{
    int left = ((int)(ch->leftvol * sfxvolume.value * 256)) >> 8;
    int right = ((int)(ch->rightvol * sfxvolume.value * 256)) >> 8;
    mq_mix16(&paintbuffer[start].left, (const int16_t *)sound->data + ch->pos, left, right, snd_ramp,
             count, ch->kill);
    ch->pos += count;
    ch->kill = qmax(0, ch->kill - count);
    mq_mixed_samples += count;
}
