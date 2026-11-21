#include "console.h"
#include <sys/resource.h>
extern void mq_clock_loop(void);
extern void mq_render_screen(void);
extern unsigned long long mq_qc_entries, mq_qc_instructions, mq_mixed_samples;
extern unsigned long long mq_hull_queries, mq_swept_traces, mq_audio_starves;
#ifdef GLQUAKE
extern unsigned long long mq_shader_batches;
#else
extern unsigned long long mq_opaque_pixels(void);
#endif
static int mq_limit, mq_fast, mq_count, mq_frames;
static double mq_last_present;
static double mq_intervals[65536];
static int mq_samples;
int mq_capture_frame;
static int mq_warmup, mq_measure_start;
static double mq_wall_start, mq_cpu_start, mq_deadline, mq_suspended;
void mq_suspend_gap(double gap) { mq_suspended += gap; }
static unsigned long long mq_starves_start;

double mq_now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static double mq_cpu(const struct rusage *usage)
{
    return usage->ru_utime.tv_sec + usage->ru_stime.tv_sec +
           (usage->ru_utime.tv_usec + usage->ru_stime.tv_usec) / 1e6;
}

static void mq_start_sample(void)
{
    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);
    mq_cpu_start = mq_cpu(&usage);
    mq_wall_start = mq_now();
    mq_starves_start = mq_audio_starves;
    mq_measure_start = mq_count;
    mq_frames = mq_samples = 0;
    mq_last_present = 0;
}
void mq_wait(int micros)
{
    if (micros > 0)
        usleep(micros);
}
void mq_draw(void)
{
    mq_render_screen();
    double now = mq_now();
    if (!mq_fast && mq_last_present && mq_samples < 65536)
        mq_intervals[mq_samples++] = 1000 * (now - mq_last_present);
    mq_last_present = now;
    ++mq_frames;
}
void mq_draw_to(double deadline)
{
    mq_deadline = deadline;
    mq_draw();
    mq_deadline = 0;
}

void mq_pace_present(void)
{
    if (mq_deadline == 0)
        return;
    double remaining;
    while ((remaining = mq_deadline - mq_now()) > 0.0003)
        usleep((int)((remaining - 0.0002) * 1000000));
    while (mq_now() < mq_deadline) {
    }
}

static int mq_compare(const void *left, const void *right)
{
    double a = *(const double *)left, b = *(const double *)right;
    return (a > b) - (a < b);
}
void mq_report(void)
{
    unsigned long long pixels = 0, batches = 0;
#ifdef GLQUAKE
    batches = mq_shader_batches;
#else
    pixels = mq_opaque_pixels();
#endif
    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);
    qsort(mq_intervals, mq_samples, sizeof(*mq_intervals), mq_compare);
    int median = mq_samples ? (mq_samples - 1) / 2 : 0;
    int p95 = mq_samples ? (mq_samples * 95 + 99) / 100 - 1 : 0;
    Con_Printf(
        "MOJO_QUAKE map=%s ticks=%d frames=%d qc_calls=%llu instructions=%llu "
        "hull_queries=%llu sweeps=%llu wall_pixels=%llu brush_batches=%llu mixed_samples=%llu "
        "frame_samples=%d median_ms=%.3f p95_ms=%.3f audio_starves=%llu peak_rss=%ld cpu_seconds=%.3f "
        "measured_ticks=%d measured_seconds=%.3f worst_ms=%.3f suspend_gap_seconds=%.3f\n",
        sv.active ? sv.name : "menu", mq_count, mq_frames, mq_qc_entries, mq_qc_instructions,
        mq_hull_queries, mq_swept_traces, pixels, batches, mq_mixed_samples, mq_samples,
        mq_intervals[median], mq_intervals[p95], mq_audio_starves - mq_starves_start, usage.ru_maxrss,
        mq_cpu(&usage) - mq_cpu_start, mq_count - mq_measure_start, mq_now() - mq_wall_start,
        mq_samples ? mq_intervals[mq_samples - 1] : 0, mq_suspended);
}
void mq_tick(float delta, int present)
{
    Host_Frame(delta);
    ++mq_count;
    if (present || mq_capture_frame)
        mq_draw();
    if (mq_limit > 0 && mq_count >= mq_limit) {
        mq_report();
        Sys_Quit();
    }
}
extern int mq_random(uint32_t *state);
uint32_t mq_server_seed = 0x51a7c0de;
int mq_server_random(void) { return mq_random(&mq_server_seed); }
void mq_reset_server_random(void) { mq_server_seed = 0x51a7c0de; }
