// Native transition regression, not whole-game parity or a training backend.
// Compile with -DTEST_MELEE to cover the second native environment.
#include <assert.h>
#include <stdio.h>
#ifdef TEST_MELEE
#include "../../ocean/holocure_melee/holocure_melee.h"
#else
#include "../../ocean/holocure/holocure.h"
#endif

int main(void) {
    float observations[108] = {0}, actions[1] = {0};
    float rewards[1] = {0}, terminals[1] = {0};
    HoloCure env = {0};
    env.observations = observations; env.actions = actions;
    env.rewards = rewards; env.terminals = terminals;
    env.player.x = env.player.y = 1920;
    env.player.hp = env.player.max_hp = 152;
    env.next_spawn_tick = 10000;
    env.n_enemies = 1;
    // Raw game discovery trace 20260907-201412, first enemy at tick 1.
    // Tick 2 is held out as expected output; c_step receives tick 1 only.
    Enemy* e = &env.enemies[0];
    e->x = 1533.647216796875f; e->y = 2021.339599609375f;
    e->spd = 0.35f; e->active = 1; e->hp = 8;
    e->dir_change_time = 1;  // Exercise recomputation at this known geometry.
    c_step(&env);
    assert(fabsf(e->direction_moving - 14.697473526000977f) < 0.0001f);
    assert(fabsf(e->x - 1533.9857177734375f) < 0.00025f);
    assert(fabsf(e->y - 2021.2508544921875f) < 0.00025f);
    // Independent geometric cases catch quadrant and axis mistakes.
    for (int dx = -1; dx <= 1; ++dx) for (int dy = -1; dy <= 1; ++dy) {
        if (!dx && !dy) continue;
        e->x = env.player.x + 100 * dx; e->y = env.player.y + 100 * dy;
        e->dir_change_time = 1;
        float before = hypotf(e->x - env.player.x, e->y - env.player.y);
        c_step(&env);
        assert(hypotf(e->x - env.player.x, e->y - env.player.y) < before);
    }
    puts("Native steering regression passed; full gameplay parity remains unverified.");
}
