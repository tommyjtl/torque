#pragma once
#include <SDL.h>
#include <stdbool.h>

// Event methods only change camera state. All GPU work stays on the draw thread.
bool inspect_open(void);
void inspect_toggle(void);
void inspect_return(void);
bool inspect_input(const SDL_Event *event);
bool inspect_prepare(SDL_Window *window, SDL_Renderer *renderer);
bool inspect_present(SDL_Renderer *renderer, unsigned lamps, const int angles[2]);
void inspect_shutdown(void);
