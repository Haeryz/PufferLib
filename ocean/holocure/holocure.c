#include "holocure.h"

int main() {
    HoloCure env;
    memset(&env, 0, sizeof(env));
    env.num_agents = 1;
    env.rng = 42;
    env.observations = (float*)calloc(OBS_SIZE, sizeof(float));
    env.actions = (float*)calloc(1, sizeof(float));
    env.rewards = (float*)calloc(1, sizeof(float));
    env.terminals = (float*)calloc(1, sizeof(float));

    c_reset(&env);
    c_render(&env);
    while (!WindowShouldClose()) {
        if (IsKeyDown(KEY_LEFT_SHIFT)) {
            if (IsKeyDown(KEY_W) || IsKeyDown(KEY_UP)) env.actions[0] = 1;
            else if (IsKeyDown(KEY_S) || IsKeyDown(KEY_DOWN)) env.actions[0] = 2;
            else if (IsKeyDown(KEY_A) || IsKeyDown(KEY_LEFT)) env.actions[0] = 3;
            else if (IsKeyDown(KEY_D) || IsKeyDown(KEY_RIGHT)) env.actions[0] = 4;
            else env.actions[0] = 0;
        } else {
            env.actions[0] = rand_r(&env.rng) % 9;
        }
        c_step(&env);
        c_render(&env);
    }
    free(env.observations);
    free(env.actions);
    free(env.rewards);
    free(env.terminals);
    c_close(&env);
}
