#include "sys.h"
/* Native file/engine adapter. Replay rows enter the same loopback movement
 * packet as live keyboard and mouse input. No entity state is set by a row. */
#include "progs.h"
#include "server.h"
#include <errno.h>
#include <math.h>
extern uint32_t mq_server_seed;
extern unsigned long long mq_qc_entries, mq_qc_instructions, mq_swept_traces;
extern uint32_t mq_hash(const byte *, int, uint32_t);
static FILE *mq_input, *mq_record;
static int mq_repeat, mq_fwd, mq_side, mq_up, mq_buttons, mq_impulse;
static float mq_yaw, mq_pitch;
static int mq_input_ticks;
static int mq_agent, mq_preview_reload;
int mq_agent_tick;
static int mq_save_tick = -1, mq_load_tick = -1;
static int mq_capture_tick = -1;
extern int mq_capture_frame;
static char mq_lastmap[64];
static int mq_lastinter;
void mq_replay_init(void)
{
    int i = COM_CheckParm("-mqsaveat");
    if (i && i + 1 < com_argc)
        mq_save_tick = atoi(com_argv[i + 1]);
    i = COM_CheckParm("-mqshotat");
    if (i && i + 1 < com_argc)
        mq_capture_tick = atoi(com_argv[i + 1]);
    i = COM_CheckParm("-mqloadat");
    if (i && i + 1 < com_argc)
        mq_load_tick = atoi(com_argv[i + 1]);
    i = COM_CheckParm("-mqreplay");
    if (i) {
        if (i + 1 >= com_argc)
            Sys_Error("Missing movement replay path");
        mq_input = !strcmp(com_argv[i + 1], "-") ? stdin : fopen(com_argv[i + 1], "r");
        if (!mq_input)
            Sys_Error("Cannot read movement replay");
    }
    mq_agent = COM_CheckParm("-mqagent");
    if (mq_agent && (mq_input != stdin || !COM_CheckParm("-mqfast")))
        Sys_Error("Agent frames require -mqfast -mqreplay -");
    if (mq_agent) {
        puts(COM_CheckParm("-mqpreview") ? "MQ_AGENT_CAPS native_save preview_rewind camera_glance" : "MQ_AGENT_CAPS native_save");
        puts("MQ_AGENT_READY 1");
        fflush(stdout);
    }
    i = COM_CheckParm("-mqrecord");
    if (i) {
        if (i + 1 >= com_argc)
            Sys_Error("Missing movement recording path");
        mq_record = fopen(com_argv[i + 1], "wx");
        if (!mq_record)
            Sys_Error("Cannot create new recording file");
    }
}
static void mq_checkpoint(const char *kind)
{
    edict_t *p = svs.clients[0].edict;
    if (!p)
        return;
    // Fingerprint gameplay fields in entity order. Strings and references are
    // normalized by ED_Write; native addresses and renderer state are excluded.
    char *bytes = NULL;
    size_t size = 0;
    FILE *mem = open_memstream(&bytes, &size);
    if (!mem)
        Sys_Error("Cannot allocate state report");
    fprintf(mem, "%s %d %.17g %u\n", sv.name, current_skill, sv.time, mq_server_seed);
    ED_WriteGlobals(mem);
    for (int i = 0; i < sv.num_edicts; i++)
        ED_Write(mem, EDICT_NUM(i));
    fclose(mem);
    uint32_t digest = mq_hash((byte *)bytes, (int)size, 2166136261u);
    free(bytes);
    printf(
        "MQ_%s map=%s command=%d time=%.9g pos=%.6f,%.6f,%.6f vel=%.6f,%.6f,%.6f yaw=%.5f pitch=%.5f "
        "hp=%.0f armor=%.0f items=%u weapon=%.0f ammo=%.0f,%.0f,%.0f,%.0f flags=%u water=%.0f "
        "intermission=%d kills=%.0f/%.0f secrets=%.0f/%.0f runes=%.0f skill=%d gravity=%.9g hash=%08x\n",
        kind, sv.name, mq_input_ticks, sv.time, p->v.origin[0], p->v.origin[1], p->v.origin[2],
        p->v.velocity[0], p->v.velocity[1], p->v.velocity[2], cl.viewangles[YAW], cl.viewangles[PITCH],
        p->v.health, p->v.armorvalue, (unsigned)p->v.items, p->v.weapon, p->v.ammo_shells,
        p->v.ammo_nails, p->v.ammo_rockets, p->v.ammo_cells, (unsigned)p->v.flags, p->v.waterlevel,
        cl.intermission, pr_global_struct->killed_monsters, pr_global_struct->total_monsters,
        pr_global_struct->found_secrets, pr_global_struct->total_secrets, pr_global_struct->serverflags,
        current_skill, sv_gravity.value, digest);
    if (COM_CheckParm("-mqexact")) {
        extern uint32_t mq_exact_digest(void);
        printf("MQ_EXACT checkpoint=%s command=%d digest=%08x\n", kind, mq_input_ticks,
               mq_exact_digest());
    }
    fflush(stdout);
}
static void mq_entities(void)
{
    for (int i = 0; i < sv.num_edicts; i++) {
        edict_t *e = EDICT_NUM(i);
        if (e->free || !e->v.classname)
            continue;
        printf("MQ_ENTITY %d %s %.5f %.5f %.5f %.5f %.0f %.0f %.0f\n", i, PR_GetString(e->v.classname),
               e->v.origin[0], e->v.origin[1], e->v.origin[2], e->v.health, e->v.solid, e->v.frame,
               e->v.flags);
    }
    puts("MQ_END");
    fflush(stdout);
}
static void mq_brushes(void)
{
    for (int i = 1; i < sv.num_edicts; ++i) {
        edict_t *e = EDICT_NUM(i);
        if (e->free || !e->v.model || e->v.solid != SOLID_BSP)
            continue;
        const char *model = PR_GetString(e->v.model);
        if (model[0] != '*')
            continue;
        printf("MQ_BRUSH %d %s %s %.6f %.6f %.6f\n", i, model, PR_GetString(e->v.classname),
               e->v.origin[0], e->v.origin[1], e->v.origin[2]);
    }
    puts("MQ_END");
    fflush(stdout);
}
static void mq_motion_state(void)
{
    int lifts = 0, shots = 0;
    for (int i = 1; i < sv.num_edicts; ++i) {
        edict_t *e = EDICT_NUM(i);
        if (e->free || (!e->v.velocity[0] && !e->v.velocity[1] && !e->v.velocity[2]))
            continue;
        const char *name = PR_GetString(e->v.classname);
        if (e->v.movetype == MOVETYPE_PUSH && strstr(name, "plat"))
            ++lifts;
        if (e->v.movetype == MOVETYPE_FLYMISSILE || e->v.movetype == MOVETYPE_BOUNCE)
            ++shots;
    }
    printf("MQ_MOTION map=%s command=%d moving_lifts=%d projectiles=%d\n", sv.name, mq_input_ticks,
           lifts, shots);
    fflush(stdout);
}
/* Record the original QuakeC encounter without changing its entities. */
static void mq_boss_events(int new_map)
{
    static int last_health;
    static unsigned active_plates;
    if (new_map) {
        last_health = -999;
        active_plates = 0;
    }
    if (strcmp(sv.name, "e1m7") || !COM_CheckParm("-mqinventory"))
        return;
    unsigned pressed = 0;
    for (int i = 0; i < sv.num_edicts; ++i) {
        const edict_t *e = EDICT_NUM(i);
        if (e->free || !e->v.classname)
            continue;
        const char *classname = PR_GetString(e->v.classname);
        if (!strcmp(classname, "monster_boss")) {
            int health = (int)e->v.health;
            if (health != last_health) {
                printf("MQ_BOSS map=e1m7 command=%d health=%d\n", mq_input_ticks, health);
                last_health = health;
            }
        } else if (!strcmp(classname, "func_button") && e->v.target && e->v.origin[2] < -0.01f) {
            const char *target = PR_GetString(e->v.target);
            const char *const targets[] = {"t12", "t13", "t14"};
            const char *const actions[] = {"north", "south", "lightning"};
            for (int j = 0; j < 3; ++j) {
                if (strcmp(target, targets[j]))
                    continue;
                unsigned bit = 1u << j;
                pressed |= bit;
                if (!(active_plates & bit))
                    printf("MQ_PLATE map=e1m7 command=%d action=%s\n", mq_input_ticks, actions[j]);
            }
        }
    }
    active_plates = pressed;
}

static void mq_move(usercmd_t *cmd, int *buttons, int *impulse)
{
    if (!mq_input && !mq_record)
        return;
    if (mq_preview_reload) {
        /* The normal load command has reconnected. mq_before_player_move has
         * restored the snapshot before this input boundary. */
        printf("MQ_RESTORE_SLOT %d\n", mq_preview_reload);
        fflush(stdout);
        mq_preview_reload = 0;
    }
    int new_map = strcmp(sv.name, mq_lastmap) != 0;
    if (new_map) {
        qstrncpy(mq_lastmap, sv.name, sizeof mq_lastmap);
        mq_checkpoint("ENTER");
        if (COM_CheckParm("-mqinventory")) {
            for (int i = 1; i < MAX_MODELS && sv.model_precache[i]; ++i)
                printf("MQ_MODEL %s %s\n", sv.name, sv.model_precache[i]);
            for (int i = 1; i < MAX_SOUNDS && sv.sound_precache[i]; ++i)
                printf("MQ_SOUND %s %s\n", sv.name, sv.sound_precache[i]);
        }
        mq_lastinter = 0;
    }
    mq_boss_events(new_map);
    if (cl.intermission && !mq_lastinter)
        mq_checkpoint("EXIT");
    if (cl.intermission > 1 && cl.intermission != mq_lastinter)
        mq_checkpoint("FINALE");
    mq_lastinter = cl.intermission;
    if (mq_input && mq_input_ticks == mq_capture_tick)
        mq_capture_frame = 1;
    if (mq_input && mq_input_ticks == mq_save_tick) {
        Cmd_ExecuteString("save replay", src_command);
        mq_checkpoint("SAVED");
        mq_motion_state();
    }
    if (mq_input && mq_input_ticks == mq_load_tick) {
        mq_load_tick = -1;
        Cbuf_AddText("load replay\n");
    }
    if (mq_input) {
        while (!mq_repeat) {
            char line[256], extra;
            if (!fgets(line, sizeof line, mq_input)) {
                if (ferror(mq_input))
                    Sys_Error("Movement replay read failed");
                mq_checkpoint("END");
                extern void mq_report(void);
                mq_report();
                Sys_Quit();
            }
            if (line[0] == '#' || line[0] == '\n')
                continue;
            if (mq_agent && COM_CheckParm("-mqpreview") && !strncmp(line, "glance ", 7)) {
                float yaw, pitch;
                if (sscanf(line + 7, "%f %f %c", &yaw, &pitch, &extra) != 2 ||
                        !isfinite(yaw) || !isfinite(pitch) || pitch < -70 || pitch > 80)
                    Sys_Error("Invalid preview camera direction");
                vec3_t previous;
                VectorCopy(cl.viewangles, previous);
                cl.viewangles[YAW] = yaw;
                cl.viewangles[PITCH] = pitch;
                mq_capture_frame = 2;
                extern void SCR_UpdateScreen(void);
                SCR_UpdateScreen();
                VectorCopy(previous, cl.viewangles);
                if (mq_capture_frame) {
                    mq_capture_frame = 0;
                    puts("MQ_GLANCE_MISSED");
                    fflush(stdout);
                }
                continue;
            }
            if (mq_agent && COM_CheckParm("-mqpreview") && !strncmp(line, "restore_slot ", 13)) {
                int slot;
                if (sscanf(line + 13, "%d %c", &slot, &extra) != 1 || slot != 1)
                    Sys_Error("Invalid preview restore slot");
                mq_preview_reload = slot;
                Cbuf_AddText("load agent_000001\n");
                memset(cmd, 0, sizeof(*cmd));
                *buttons = *impulse = 0;
                return;
            }
            if (mq_agent && !strncmp(line, "save_slot ", 10)) {
                int slot;
                if (sscanf(line + 10, "%d %c", &slot, &extra) != 1 || slot < 1 || slot > 999999)
                    Sys_Error("Invalid agent save slot");
                char command[40];
                snprintf(command, sizeof command, "save agent_%06d", slot);
                Cmd_ExecuteString(command, src_command);
                printf("MQ_SAVE_SLOT %d\n", slot);
                fflush(stdout);
                continue;
            }
            if (!strcmp(line, "motion\n")) {
                mq_motion_state();
                continue;
            }
            if (!strcmp(line, "state\n")) {
                mq_checkpoint("STATE");
                continue;
            }
            if (!strcmp(line, "brushes\n")) {
                mq_brushes();
                continue;
            }
            if (!strcmp(line, "entities\n")) {
                mq_entities();
                continue;
            }
            if (sscanf(line, "%d %d %d %d %f %f %d %d %c", &mq_repeat, &mq_fwd, &mq_side, &mq_up,
                       &mq_yaw, &mq_pitch, &mq_buttons, &mq_impulse, &extra) != 8 ||
                mq_repeat < 1 || mq_repeat > 100000 || abs(mq_fwd) > 400 || abs(mq_side) > 400 ||
                abs(mq_up) > 400 || !isfinite(mq_yaw) || fabsf(mq_yaw) > 360 || !isfinite(mq_pitch) ||
                mq_pitch < -70 || mq_pitch > 80 || mq_buttons < 0 || mq_buttons > 3 || mq_impulse < 0 ||
                mq_impulse > 12 || mq_impulse == 9 || mq_impulse == 11)
                Sys_Error("Invalid movement command at tick %d", mq_input_ticks);
        }
        cmd->forwardmove = mq_fwd;
        cmd->sidemove = mq_side;
        cmd->upmove = mq_up;
        cl.viewangles[YAW] = mq_yaw;
        cl.viewangles[PITCH] = mq_pitch;
        cl.viewangles[ROLL] = 0;
        *buttons = mq_buttons;
        *impulse = mq_impulse;
        --mq_repeat;
        if (mq_agent && !mq_repeat) {
            mq_agent_tick = mq_input_ticks + 1;
            mq_capture_frame |= 2;
        }
    }
    if (mq_record)
        fprintf(mq_record, "1 %d %d %d %.8g %.8g %d %d\n", (int)cmd->forwardmove, (int)cmd->sidemove,
                (int)cmd->upmove, cl.viewangles[YAW], cl.viewangles[PITCH], *buttons, *impulse);
    mq_input_ticks++;
}
