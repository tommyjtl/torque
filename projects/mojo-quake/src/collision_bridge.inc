extern int mq_sweep(const int32_t *, const float *, const byte *, int, int, int, const float *,
                    const float *, int32_t *, float *);
unsigned long long mq_swept_traces;
qboolean Mod_TraceHull(const hull_t *hull, int node, const vec3_t start, const vec3_t end,
                       trace_t *trace)
{
    int32_t flags[] = {trace->allsolid, trace->startsolid, trace->inopen, trace->inwater};
    float values[8] = {trace->fraction,        trace->endpos[0],       trace->endpos[1],
                       trace->endpos[2],       trace->plane.normal[0], trace->plane.normal[1],
                       trace->plane.normal[2], trace->plane.dist};
    ++mq_swept_traces;
    int result = mq_sweep((const int32_t *)hull->clipnodes, (const float *)hull->planes,
                          (const byte *)hull->planes, hull->firstclipnode, hull->lastclipnode, node,
                          start, end, flags, values);
    if (result < 0)
        SV_Error("Invalid BSP collision hull");
    trace->allsolid = flags[0];
    trace->startsolid = flags[1];
    trace->inopen = flags[2];
    trace->inwater = flags[3];
    trace->fraction = values[0];
    memcpy(trace->endpos, values + 1, sizeof trace->endpos);
    memcpy(trace->plane.normal, values + 4, sizeof trace->plane.normal);
    trace->plane.dist = values[7];
    return result;
}
