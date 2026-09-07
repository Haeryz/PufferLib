// HoloCure Stage 1 (Suisei / AxeSwing) — PufferLib 4 native environment.
//
// Headless reconstruction of HoloCure v0.7.1746645739 mined from
// tools/holocure_reference/local (dynamics.json, suisei.json, geometry.json,
// and the 1147-tick canonical_game.jsonl trace). Player movement, enemy
// spawn schedule, enemy movement AI, and attack lifecycle are reproduced
// from measured values; combat/XP/leveling use extracted coefficients and
// remain unresolved until a combat trace is available. See the Python
// package holocure_rl/holocure/constants.py for full provenance.
//
// Single agent, Discrete(9) movement (0=stop, 1=up..8=down-right), 60 Hz.
#include <stdlib.h>
#include <math.h>
#include <stdio.h>
#include "raylib.h"

#define MAX_ENEMIES 64
#define OBS_ENEMIES 24

// Mined constants (see holocure_rl/holocure/constants.py for provenance).
#define MAP_W 2500.0f
#define MAP_H 2500.0f
#define PLAYER_START_X 1920.0f
#define PLAYER_START_Y 1920.0f
#define PLAYER_HP 152.0f
#define PLAYER_SPD 2.259999999999999f
#define PLAYER_ATK 1.3f
#define PLAYER_IMAGE_SPEED 0.08333333333f   // 1/12 per tick (trace)
#define ENEMY_HP 8.0f
#define ENEMY_SPD 0.35f
#define ENEMY_XP 6.0f
#define ENEMY_WIDTH 32.0f
#define DIR_CHANGE_TIME 3
#define VIEW_CHECK 5
#define ENEMY_IMAGE_SPEED 0.1f
#define SPAWN_INTERVAL 180
#define SPAWN_COUNT 7
#define SPAWN_MIN_R 350.0f
#define SPAWN_MAX_R 660.0f
#define WEAPON_PERIOD 74
#define WEAPON_IMAGE_SPEED 0.4166666667f   // 5/12 per tick (trace)
#define WEAPON_FRAMES 8                    // destroy when image_index >= 8
#define WEAPON_RANGE 320.0f
#define WEAPON_SRAD 50.0f
#define WEAPON_HIT_CD 30
#define WEAPON_DAMAGE 1.2f
#define WEAPON_START_Y -16.0f
#define WEAPON_MAX_LEVEL 7
#define DIAG 0.7071067811865476f

static inline float clipf(float v, float lo, float hi) {
    return fmaxf(fminf(v, hi), lo);
}

// Log must be the first Env field; its last field must be `float n`.
typedef struct { float perf, score, episode_return, episode_length, n; } Log;

typedef struct {
    float x, y, hp, max_hp, spd, exp;
    int wlevel, is_moving, alive_for, invincibility_timer;
    float special_timer, special_meter, direction, image_index;
} Player;

typedef struct {
    float x, y, hp, max_hp, spd;
    int active, hit_cd, spawned_time, alive_for, dir_change_time, view_check;
    float direction_moving, image_index;
} Enemy;

typedef struct {
    float x, y, image_index;
    int level, active;
} Attack;

typedef struct {
    Log log;                                   // required first
    int num_agents;                            // required
    unsigned int rng;                           // required
    float *observations, *actions, *rewards, *terminals;  // required
    Player player;
    Enemy enemies[MAX_ENEMIES];
    int n_enemies;
    Attack attack;
    int attack_timer;
    int next_spawn_tick;
    int step_count;
    int total_kills;
    int save_frames;
} HoloCure;

// Movement table: action 0-8 -> (dx, dy). y axis: up = negative.
static void move_delta(int action, float* dx, float* dy) {
    switch (action) {
        case 0: *dx = 0.0f;        *dy = 0.0f;        break;  // stop
        case 1: *dx = 0.0f;        *dy = -1.0f;       break;  // up
        case 2: *dx = 0.0f;        *dy = 1.0f;        break;  // down
        case 3: *dx = -1.0f;       *dy = 0.0f;        break;  // left
        case 4: *dx = 1.0f;        *dy = 0.0f;        break;  // right
        case 5: *dx = -DIAG;       *dy = -DIAG;       break;  // up-left
        case 6: *dx = DIAG;        *dy = -DIAG;       break;  // up-right
        case 7: *dx = -DIAG;       *dy = DIAG;        break;  // down-left
        case 8: *dx = DIAG;        *dy = DIAG;        break;  // down-right
        default: *dx = 0.0f;       *dy = 0.0f;        break;
    }
}

// GameMaker point_direction: degrees(atan2(y1-y2, x2-x1)).
static float point_direction(float x1, float y1, float x2, float y2) {
    float d = atan2f(y1 - y2, x2 - x1) * 180.0f / (float)M_PI;
    if (d < 0.0f) d += 360.0f;
    return d;
}

static void compute_observations(HoloCure* env) {
    float* obs = env->observations;
    int idx = 0;
    Player* p = &env->player;
    obs[idx++] = p->x / MAP_W;
    obs[idx++] = p->y / MAP_H;
    obs[idx++] = p->hp / p->max_hp;
    obs[idx++] = p->spd;
    obs[idx++] = p->exp;
    obs[idx++] = (float)p->wlevel;
    obs[idx++] = p->special_meter;
    obs[idx++] = (float)p->is_moving;
    // Attack
    obs[idx++] = (float)env->attack.active;
    obs[idx++] = env->attack.active ? env->attack.x / MAP_W : 0.0f;
    obs[idx++] = env->attack.active ? env->attack.y / MAP_H : 0.0f;
    obs[idx++] = env->attack.active ? (float)env->attack.level / WEAPON_MAX_LEVEL : 0.0f;
    // Enemies (first OBS_ENEMIES active; pad with zeros).
    int written = 0;
    for (int i = 0; i < MAX_ENEMIES && written < OBS_ENEMIES; i++) {
        Enemy* e = &env->enemies[i];
        if (!e->active) continue;
        obs[idx++] = e->x / MAP_W;
        obs[idx++] = e->y / MAP_H;
        obs[idx++] = e->hp / ENEMY_HP;
        obs[idx++] = e->direction_moving / 360.0f;
        written++;
    }
    for (; written < OBS_ENEMIES; written++) {
        obs[idx++] = 0.0f; obs[idx++] = 0.0f; obs[idx++] = 0.0f; obs[idx++] = 0.0f;
    }
}

static void spawn_wave(HoloCure* env, int count, int tick) {
    for (int k = 0; k < count; k++) {
        int slot = -1;
        for (int i = 0; i < MAX_ENEMIES; i++) {
            if (!env->enemies[i].active) { slot = i; break; }
        }
        if (slot < 0) break;
        Enemy* e = &env->enemies[slot];
        float ang = (rand_r(&env->rng) / (float)RAND_MAX) * 2.0f * (float)M_PI;
        float r = SPAWN_MIN_R + (rand_r(&env->rng) / (float)RAND_MAX) * (SPAWN_MAX_R - SPAWN_MIN_R);
        e->x = clipf(env->player.x + r * cosf(ang), 0.0f, MAP_W);
        e->y = clipf(env->player.y + r * sinf(ang), 0.0f, MAP_H);
        e->hp = ENEMY_HP; e->max_hp = ENEMY_HP; e->spd = ENEMY_SPD;
        e->active = 1; e->hit_cd = 0;
        e->spawned_time = tick; e->alive_for = 0;
        e->dir_change_time = DIR_CHANGE_TIME; e->view_check = VIEW_CHECK;
        e->image_index = 0.1f;
        e->direction_moving = point_direction(e->x, e->y, env->player.x, env->player.y);
        env->n_enemies++;
    }
}

void c_reset(HoloCure* env) {
    env->player.x = PLAYER_START_X; env->player.y = PLAYER_START_Y;
    env->player.hp = PLAYER_HP; env->player.max_hp = PLAYER_HP;
    env->player.spd = PLAYER_SPD; env->player.exp = 0.2f;
    env->player.wlevel = 1; env->player.is_moving = 0;
    env->player.alive_for = 0; env->player.invincibility_timer = 0;
    env->player.special_timer = 1.0f; env->player.special_meter = 0.0f;
    env->player.direction = 0.0f; env->player.image_index = 1.0f;
    for (int i = 0; i < MAX_ENEMIES; i++) env->enemies[i].active = 0;
    env->n_enemies = 0;
    env->attack.active = 0; env->attack.x = 0; env->attack.y = 0;
    env->attack.image_index = 0.0f; env->attack.level = 1;
    env->attack_timer = 0;
    env->step_count = 0; env->total_kills = 0;
    env->log.perf = 0; env->log.score = 0;
    env->log.episode_return = 0; env->log.episode_length = 0; env->log.n = 0;
    // First wave at tick 1 (canonical trace: tick 1 -> 7 enemies).
    spawn_wave(env, SPAWN_COUNT, 1);
    env->next_spawn_tick = 1 + SPAWN_INTERVAL;
    compute_observations(env);
}

void c_step(HoloCure* env) {
    int action = (int)env->actions[0];
    if (action < 0) action = 0; if (action > 8) action = 8;
    float dx, dy;
    move_delta(action, &dx, &dy);
    Player* p = &env->player;
    if (dx == 0.0f && dy == 0.0f) {
        p->is_moving = 0; p->direction = 0.0f;
    } else {
        p->is_moving = 1;
        p->direction = atan2f(-dy, dx) * 180.0f / (float)M_PI;
        if (p->direction < 0.0f) p->direction += 360.0f;
        p->x = clipf(p->x + dx * p->spd, 0.0f, MAP_W);
        p->y = clipf(p->y + dy * p->spd, 0.0f, MAP_H);
    }
    p->image_index += PLAYER_IMAGE_SPEED;
    p->alive_for++;
    p->special_timer += 1.0f;
    if (p->invincibility_timer > 0) p->invincibility_timer--;

    // Enemies: move toward player, recalc direction every DIR_CHANGE_TIME ticks.
    for (int i = 0; i < MAX_ENEMIES; i++) {
        Enemy* e = &env->enemies[i];
        if (!e->active) continue;
        e->alive_for++;
        e->dir_change_time--;
        if (e->dir_change_time <= 0) {
            e->dir_change_time = DIR_CHANGE_TIME;
            e->direction_moving = point_direction(e->x, e->y, p->x, p->y);
        }
        e->view_check = (e->view_check - 1 + (VIEW_CHECK + 1)) % (VIEW_CHECK + 1);
        float rad = e->direction_moving * (float)M_PI / 180.0f;
        e->x += e->spd * cosf(rad);
        e->y -= e->spd * sinf(rad);
        e->image_index += ENEMY_IMAGE_SPEED;
        if (e->hit_cd > 0) e->hit_cd--;
    }

    // Weapon: create every WEAPON_PERIOD ticks, destroy when animation ends.
    env->attack_timer++;
    if (!env->attack.active) {
        if (env->attack_timer >= WEAPON_PERIOD) {
            env->attack.active = 1;
            env->attack.x = p->x; env->attack.y = p->y + WEAPON_START_Y;
            env->attack.image_index = 0.0f; env->attack.level = p->wlevel;
            env->attack_timer = 0;
        }
    } else {
        env->attack.x = p->x; env->attack.y = p->y + WEAPON_START_Y;
        env->attack.image_index += WEAPON_IMAGE_SPEED;
        if (env->attack.image_index >= (float)WEAPON_FRAMES) {
            env->attack.active = 0; env->attack.image_index = 0.0f;
        }
    }

    // Combat: melee damage to enemies in range (UNRESOLVED damage formula).
    float reward = -0.001f;  // tiny time penalty
    if (env->attack.active) {
        float dmg = PLAYER_ATK * WEAPON_DAMAGE;
        for (int i = 0; i < MAX_ENEMIES; i++) {
            Enemy* e = &env->enemies[i];
            if (!e->active || e->hit_cd > 0) continue;
            float dist = sqrtf((e->x - env->attack.x) * (e->x - env->attack.x)
                             + (e->y - env->attack.y) * (e->y - env->attack.y));
            if (dist <= WEAPON_RANGE) {
                e->hp -= dmg;
                e->hit_cd = WEAPON_HIT_CD;
                if (e->hp <= 0.0f) {
                    e->active = 0; env->n_enemies--; env->total_kills++;
                    reward += 1.0f;
                    env->log.perf += 1.0f; env->log.n += 1.0f;
                }
            }
        }
    }

    // Spawner
    if (env->step_count + 1 >= env->next_spawn_tick) {
        int count = SPAWN_COUNT;
        if (rand_r(&env->rng) % 100 < 15) count = 9;  // occasional bigger wave
        spawn_wave(env, count, env->step_count + 1);
        env->next_spawn_tick = env->step_count + 1 + SPAWN_INTERVAL;
        if (rand_r(&env->rng) % 100 < 8) {            // occasional double-spawn
            spawn_wave(env, SPAWN_COUNT, env->step_count + 2);
        }
    }

    env->rewards[0] = reward;
    env->log.episode_return += reward;
    env->log.episode_length += 1.0f;

    int dead = p->hp <= 0.0f;
    env->terminals[0] = dead ? 1.0f : 0.0f;
    if (dead) env->log.score = env->log.episode_return;

    env->step_count++;
    compute_observations(env);
}

void c_render(HoloCure* env) {
    if (!IsWindowReady()) {
        InitWindow(900, 900, "HoloCure Melee - PufferLib");
        SetTargetFPS(60);
    }
    if (IsKeyDown(KEY_ESCAPE)) exit(0);
    BeginDrawing();
    ClearBackground((Color){10, 12, 20, 255});
    float sx = 900.0f / MAP_W, sy = 900.0f / MAP_H;

    // Grid for visibility
    for (int i = 0; i <= 5; i++) {
        DrawLine(i * 900/5, 0, i * 900/5, 900, (Color){30, 30, 40, 255});
        DrawLine(0, i * 900/5, 900, i * 900/5, (Color){30, 30, 40, 255});
    }

    Player* p = &env->player;
    // Attack range (yellow circle)
    if (env->attack.active)
        DrawCircleLinesV((Vector2){p->x * sx, p->y * sy},
                         WEAPON_RANGE * sx, (Color){255, 220, 120, 200});
    // Enemies (red, bigger)
    for (int i = 0; i < MAX_ENEMIES; i++) {
        Enemy* e = &env->enemies[i];
        if (!e->active) continue;
        DrawCircleV((Vector2){e->x * sx, e->y * sy}, 8, (Color){255, 80, 80, 255});
    }
    // Player (blue, bigger, with outline)
    DrawCircleV((Vector2){p->x * sx, p->y * sy}, 14, (Color){80, 200, 255, 255});
    DrawCircleLinesV((Vector2){p->x * sx, p->y * sy}, 14, (Color){255, 255, 255, 255});

    // HUD
    DrawText(TextFormat("HP %.0f  Kills %d  Step %d  Enemies %d",
             p->hp, env->total_kills, env->step_count, env->n_enemies),
             10, 10, 20, RAYWHITE);
    DrawText(TextFormat("Action %.0f", env->actions[0]), 10, 35, 20, GREEN);
    DrawText("ESC to quit", 10, 870, 16, (Color){100, 100, 100, 255});
    EndDrawing();

    // Save frames for eval_gif.py
    if (getenv("SAVE_FRAMES")) {
        static int frame_num = 0;
        char fname[64];
        snprintf(fname, sizeof(fname), "frame_%04d.png", frame_num++);
        TakeScreenshot(fname);
    }
}

void c_close(HoloCure* env) {
    (void)env;
    if (IsWindowReady()) CloseWindow();
}
