/* GPL-2.0-or-later. Engine storage and builtin calls for the Mojo QuakeC VM. */
extern int mq_validate_code(const dstatement_t *, int, int);
extern int mq_execute(const dstatement_t *, int32_t *, float *, int, int, int);
unsigned long long mq_qc_instructions, mq_qc_entries;

static int mq_inventory_enabled;
static byte mq_seen_builtin[256];

void mq_begin_inventory(void)
{
    mq_inventory_enabled = COM_CheckParm("-mqinventory") != 0;
    memset(mq_seen_builtin, 0, sizeof(mq_seen_builtin));
}

void mq_statement(int pc)
{
    pr_xstatement = pc;
    pr_xfunction->profile++;
}

int mq_string_compare(int left, int right) { return strcmp(PR_GetString(left), PR_GetString(right)); }

int mq_field_address(int entity, int field, int width, int writing)
{
    if (entity < 0 || entity % pr_edict_size || entity / pr_edict_size >= sv.num_edicts || field < 0 ||
        field > progs->entityfields - width)
        PR_RunError("QuakeC entity field outside active map storage");
    if (writing && !entity && sv.state == ss_active)
        PR_RunError("QuakeC attempted to modify the active world");
    return entity + (int)offsetof(edict_t, v) + field * 4;
}

int32_t *mq_entity_words(int address, int width)
{
    int local = address >= 0 ? address % pr_edict_size : -1;
    if (address < 0 || address % 4 || address / pr_edict_size >= sv.num_edicts ||
        local < (int)offsetof(edict_t, v) ||
        local > (int)offsetof(edict_t, v) + 4 * (progs->entityfields - width))
        PR_RunError("Invalid QuakeC field reference");
    return (int32_t *)((byte *)sv.edicts + address);
}

int mq_call(int function, int args)
{
    if (function <= 0 || function >= progs->numfunctions)
        PR_RunError("Invalid QuakeC function %d", function);
    pr_argc = args;
    dfunction_t *callee = &pr_functions[function];
    if (callee->first_statement >= 0)
        return PR_EnterFunction(callee) + 1;
    int builtin = -callee->first_statement;
    if (builtin >= pr_numbuiltins)
        PR_RunError("Unknown QuakeC builtin %d", builtin);
    if (mq_inventory_enabled && (unsigned)builtin < sizeof(mq_seen_builtin) &&
        !mq_seen_builtin[builtin]) {
        mq_seen_builtin[builtin] = 1;
        printf("MQ_BUILTIN %s %d %s\n", sv.name, builtin, PR_GetString(callee->s_name));
    }
    pr_builtins[builtin]();
    return -1;
}

int mq_return(int initial_depth)
{
    int next = PR_LeaveFunction() + 1;
    return pr_depth == initial_depth ? -1 : next;
}

void mq_state(float frame, int think)
{
    edict_t *self = PROG_TO_EDICT(pr_global_struct->self);
    self->v.frame = frame;
    self->v.think = think;
    self->v.nextthink = pr_global_struct->time + 0.1;
}

void PR_ExecuteProgram(func_t function)
{
    if (function <= 0 || function >= progs->numfunctions)
        PR_RunError("Invalid QuakeC entry %d", function);
    int depth = pr_depth;
    int pc = PR_EnterFunction(&pr_functions[function]) + 1;
    int steps =
        mq_execute(pr_statements, (int32_t *)pr_globals, pr_globals, pc, progs->numstatements, depth);
    if (steps <= 0)
        PR_RunError("Mojo QuakeC VM stopped at statement %d (status %d)", pr_xstatement, steps);
    mq_qc_entries++;
    mq_qc_instructions += (unsigned)steps;
}
