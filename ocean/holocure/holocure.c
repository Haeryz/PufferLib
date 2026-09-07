// Standalone raylib executable for the HoloCure environment.
// Build:  bash build.sh holocure --local   (debug + sanitizers)
//         bash build.sh holocure --fast    (optimized)
//
// Runs the env with keyboard control (WASD) and raylib rendering. This is a
// development/visualization harness; training uses the _C.so built by the
// default `bash build.sh holocure --float` path (binding.c + holocure.h).
#include "holocure.h"

int main(void) {
    HoloCure env;
    env.rng = 42;
    env.num_agents = 1;
    env.save_frames = 0;
    float obs[108];   // 8 (player) + 4 (attack) + 24*4 (enemies); matches binding.c
    float actions[1];
    float rewards[1];
    float terminals[1];
    env.observations = obs;
    env.actions = actions;
    env.rewards = rewards;
    env.terminals = terminals;
    actions[0] = 0.0f;

    InitWindow(900, 900, "HoloCure - PufferLib");
    SetTargetFPS(60);
    c_reset(&env);

    while (!WindowShouldClose()) {
        // Keyboard -> Discrete(9). y axis: up = negative (W).
        int a = 0;
        int w = IsKeyDown(KEY_W), s = IsKeyDown(KEY_S);
        int l = IsKeyDown(KEY_A), r = IsKeyDown(KEY_D);
        if (w && r) a = 6; else if (w && l) a = 5;
        else if (s && l) a = 7; else if (s && r) a = 8;
        else if (w) a = 1; else if (s) a = 2;
        else if (l) a = 3; else if (r) a = 4;
        actions[0] = (float)a;
        c_step(&env);
        c_render(&env);
        if (terminals[0] > 0.0f) {
            c_reset(&env);
        }
    }
    c_close(&env);
    return 0;
}
