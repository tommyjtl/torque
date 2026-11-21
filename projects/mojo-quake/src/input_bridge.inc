#include "cmd.h"
extern int mq_key_action(int scan, int menu);
static byte mq_held[SDL_NUM_SCANCODES];

static void mq_action(int action, int scan, int down)
{
    static const char *const movement[] = {"forward", "back",  "moveleft", "moveright",
                                           "left",    "right", "attack",   "jump"};
    static const int menu_keys[] = {K_UPARROW, K_DOWNARROW, K_LEFTARROW, K_RIGHTARROW, K_ENTER};
    const char *name = NULL;
    if (action >= 8 && action <= 15)
        name = movement[action - 8];
    if (action == 19)
        name = "lookup";
    if (action == 20)
        name = "lookdown";
    if (name) {
        char cmd[64];
        qsnprintf(cmd, sizeof(cmd), "%c%s %d\n", down ? '+' : '-', name, 400 + scan);
        Cbuf_AddText("%s", cmd);
    } else if (action >= 3 && action <= 7)
        Key_Event(menu_keys[action - 3], down);
    else if (down) {
        if (action == 1)
            Sys_Quit();
        else if (action == 2)
            M_ToggleMenu_f();
        else if (action == 16)
            Cbuf_AddText("impulse 10\n");
        else if (action == 17)
            Cbuf_AddText("save quick\n");
        else if (action == 18)
            Cbuf_AddText("load quick\n");
    }
}

static qboolean mq_key(const SDL_KeyboardEvent *event)
{
    int scan = event->keysym.scancode;
    if (scan <= 0 || scan >= SDL_NUM_SCANCODES)
        return false;
    int down = event->type == SDL_KEYDOWN;
    int action = mq_held[scan];
    if (!action && !down)
        return false;
    if (down) {
        if (!action)
            action = mq_key_action(scan, key_dest != key_game);
        if (!action)
            return false;
        if (mq_held[scan] || event->repeat)
            return true;
        mq_held[scan] = action;
    } else
        mq_held[scan] = 0;
    mq_action(action, scan, down);
    return true;
}

static void mq_clear_keys(void)
{
    for (int scan = 0; scan < SDL_NUM_SCANCODES; ++scan) {
        if (mq_held[scan])
            mq_action(mq_held[scan], scan, 0);
        mq_held[scan] = 0;
    }
    Key_ClearAllStates();
}
