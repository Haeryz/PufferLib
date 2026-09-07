#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <stdio.h>
#include "raylib.h"

#define MAP_W 1600.0f
#define MAP_H 1600.0f
#define PLAYER_RADIUS 12.0f
#define PLAYER_BASE_SPEED 3.2f
#define PLAYER_BASE_HP 100.0f
#define INVULN_FRAMES 30
#define CONTACT_DAMAGE_CD 20

#define MAX_ENEMIES 400
#define MAX_GEMS 1024
#define MAX_PROJECTILES 200
#define N_NEAREST_ENEMIES 16
#define N_NEAREST_GEMS 8
#define N_SECTORS 8
#define OBS_RANGE 500.0f

#define WEAPON_MAX_LEVEL 7
#define WEAPON_BASE_CD 28
#define WEAPON_BASE_DMG 10.0f
#define WEAPON_PROJ_SPEED 7.0f
#define WEAPON_PROJ_LIFE 120

#define MAX_LEVEL 30
#define GEM_PICKUP_RADIUS 90.0f
#define GEM_MAGNET_SPEED 8.0f

#define MAX_STEPS 1200
#define SPAWN_INTERVAL_BASE 14

#define OBS_SIZE 108

static const float MOVE_TABLE[9][2] = {
    {0.0f, 0.0f},      {0.0f, -1.0f},    {0.0f, 1.0f},
    {-1.0f, 0.0f},     {1.0f, 0.0f},
    {-0.7071f, -0.7071f}, {0.7071f, -0.7071f},
    {-0.7071f, 0.7071f},  {0.7071f, 0.7071f}
};

typedef struct {
    float x, y, hp, max_hp;
    int type;
    int active;
} Enemy;

typedef struct {
    float x, y;
    int value;
    int active;
} Gem;

typedef struct {
    float x, y, dx, dy;
    int life;
    int active;
} Projectile;

typedef struct {
    float score;
    float episode_return;
    float episode_length;
    float kills;
    float level;
    float n;
} Log;

typedef struct {
    Log log;
    float* observations;
    float* actions;
    float* rewards;
    float* terminals;
    int num_agents;
    unsigned int rng;

    float px, py, hp, max_hp, speed, pickup_range;
    int level, xp, xp_needed, invuln, contact_cd, kills;
    int weapon_level, weapon_cd, proj_count;
    float weapon_dmg;
    int step_count;
    int alive;
    int spawn_timer;
    int save_frames;
    int screenshot_count;

    Enemy enemies[MAX_ENEMIES];
    int n_enemies;
    Gem gems[MAX_GEMS];
    int n_gems;
    Projectile projectiles[MAX_PROJECTILES];
    int n_projectiles;
} HoloCure;

static float randf(unsigned int* rng) {
    return (float)rand_r(rng) / (float)RAND_MAX;
}

static int xp_for_level(int lvl) {
    return 5 + lvl * 5;
}

static void spawn_enemy(HoloCure* env, int type, float difficulty) {
    if (env->n_enemies >= MAX_ENEMIES) return;
    float angle = randf(&env->rng) * 2.0f * M_PI;
    float dist = 350.0f + randf(&env->rng) * 150.0f;
    int idx = env->n_enemies;
    env->enemies[idx].x = env->px + cosf(angle) * dist;
    env->enemies[idx].y = env->py + sinf(angle) * dist;
    if (env->enemies[idx].x < 0) env->enemies[idx].x = 0;
    if (env->enemies[idx].x > MAP_W) env->enemies[idx].x = MAP_W;
    if (env->enemies[idx].y < 0) env->enemies[idx].y = 0;
    if (env->enemies[idx].y > MAP_H) env->enemies[idx].y = MAP_H;

    float hp_base[3] = {8.0f, 4.0f, 24.0f};
    env->enemies[idx].hp = hp_base[type] * difficulty;
    env->enemies[idx].max_hp = env->enemies[idx].hp;
    env->enemies[idx].type = type;
    env->enemies[idx].active = 1;
    env->n_enemies++;
}

static void maybe_spawn_enemies(HoloCure* env) {
    env->spawn_timer++;
    float difficulty = 1.0f + (float)env->step_count / 300.0f;
    int interval = SPAWN_INTERVAL_BASE / (int)difficulty;
    if (interval < 4) interval = 4;
    if (env->spawn_timer < interval) return;
    env->spawn_timer = 0;
    if (env->n_enemies >= MAX_ENEMIES) return;

    int count = (int)(3 + difficulty * 2);
    if (count > MAX_ENEMIES - env->n_enemies) count = MAX_ENEMIES - env->n_enemies;

    for (int i = 0; i < count; i++) {
        float r = randf(&env->rng);
        int type;
        if (env->step_count > 600 && r < 0.05f) type = 2;
        else if (r < 0.3f) type = 1;
        else type = 0;
        spawn_enemy(env, type, difficulty);
    }
}

static void update_enemies(HoloCure* env) {
    float speeds[3] = {1.2f, 2.2f, 0.7f};
    for (int i = 0; i < env->n_enemies; i++) {
        if (!env->enemies[i].active) continue;
        float dx = env->px - env->enemies[i].x;
        float dy = env->py - env->enemies[i].y;
        float dist = sqrtf(dx*dx + dy*dy) + 1e-6f;
        float speed = speeds[env->enemies[i].type];
        env->enemies[i].x += dx / dist * speed;
        env->enemies[i].y += dy / dist * speed;
    }
}

static void fire_weapon(HoloCure* env) {
    if (env->weapon_cd > 0) return;
    if (env->n_enemies == 0) return;

    int nearest = -1;
    float nearest_dist = 1e30f;
    for (int i = 0; i < env->n_enemies; i++) {
        if (!env->enemies[i].active) continue;
        float dx = env->enemies[i].x - env->px;
        float dy = env->enemies[i].y - env->py;
        float d = dx*dx + dy*dy;
        if (d < nearest_dist) { nearest_dist = d; nearest = i; }
    }
    if (nearest < 0) return;

    float tx = env->enemies[nearest].x - env->px;
    float ty = env->enemies[nearest].y - env->py;
    float td = sqrtf(tx*tx + ty*ty) + 1e-6f;
    float ndx = tx / td, ndy = ty / td;

    int cd = WEAPON_BASE_CD * (1.0f - 0.12f * (env->weapon_level - 1));
    if (cd < 6) cd = 6;
    env->weapon_cd = cd;

    int n_shots = env->proj_count;
    float spread = 0.15f;
    for (int i = 0; i < n_shots; i++) {
        if (env->n_projectiles >= MAX_PROJECTILES) break;
        float offset = ((float)i - (float)(n_shots - 1) / 2.0f) * spread;
        float ca = cosf(offset), sa = sinf(offset);
        int idx = env->n_projectiles;
        env->projectiles[idx].x = env->px;
        env->projectiles[idx].y = env->py;
        env->projectiles[idx].dx = (ndx * ca - ndy * sa) * WEAPON_PROJ_SPEED;
        env->projectiles[idx].dy = (ndx * sa + ndy * ca) * WEAPON_PROJ_SPEED;
        env->projectiles[idx].life = WEAPON_PROJ_LIFE;
        env->projectiles[idx].active = 1;
        env->n_projectiles++;
    }
}

static void update_projectiles(HoloCure* env) {
    float kill_reward = 0.0f;
    int xp_vals[3] = {3, 2, 8};

    for (int i = 0; i < env->n_projectiles; i++) {
        if (!env->projectiles[i].active) continue;
        env->projectiles[i].x += env->projectiles[i].dx;
        env->projectiles[i].y += env->projectiles[i].dy;
        env->projectiles[i].life--;

        if (env->projectiles[i].life <= 0 ||
            env->projectiles[i].x < -20 || env->projectiles[i].x > MAP_W + 20 ||
            env->projectiles[i].y < -20 || env->projectiles[i].y > MAP_H + 20) {
            env->projectiles[i].active = 0;
            continue;
        }

        float pr = 16.0f;
        for (int j = 0; j < env->n_enemies; j++) {
            if (!env->enemies[j].active) continue;
            float dx = env->enemies[j].x - env->projectiles[i].x;
            float dy = env->enemies[j].y - env->projectiles[i].y;
            if (dx*dx + dy*dy < pr*pr) {
                env->enemies[j].hp -= env->weapon_dmg;
                env->projectiles[i].active = 0;
                if (env->enemies[j].hp <= 0) {
                    env->enemies[j].active = 0;
                    if (env->n_gems < MAX_GEMS) {
                        int gi = env->n_gems;
                        env->gems[gi].x = env->enemies[j].x;
                        env->gems[gi].y = env->enemies[j].y;
                        env->gems[gi].value = xp_vals[env->enemies[j].type];
                        env->gems[gi].active = 1;
                        env->n_gems++;
                    }
                    env->kills++;
                    kill_reward += 1.0f;
                }
                break;
            }
        }
    }

    env->rewards[0] += kill_reward;

    for (int i = 0; i < env->n_projectiles; i++) {
        if (!env->projectiles[i].active) {
            env->projectiles[i] = env->projectiles[env->n_projectiles - 1];
            env->n_projectiles--;
            i--;
        }
    }
    for (int i = 0; i < env->n_enemies; i++) {
        if (!env->enemies[i].active) {
            env->enemies[i] = env->enemies[env->n_enemies - 1];
            env->n_enemies--;
            i--;
        }
    }
}

static float check_contact_damage(HoloCure* env) {
    if (env->invuln > 0 || env->contact_cd > 0 || env->n_enemies == 0) return 0.0f;
    float dmg_vals[3] = {6.0f, 4.0f, 10.0f};
    float contact_r = PLAYER_RADIUS + 14.0f;
    for (int i = 0; i < env->n_enemies; i++) {
        if (!env->enemies[i].active) continue;
        float dx = env->enemies[i].x - env->px;
        float dy = env->enemies[i].y - env->py;
        if (dx*dx + dy*dy < contact_r*contact_r) {
            env->contact_cd = CONTACT_DAMAGE_CD;
            return dmg_vals[env->enemies[i].type];
        }
    }
    return 0.0f;
}

static int update_gems(HoloCure* env) {
    if (env->n_gems == 0) return 0;
    int xp_gain = 0;
    for (int i = 0; i < env->n_gems; i++) {
        if (!env->gems[i].active) continue;
        float dx = env->px - env->gems[i].x;
        float dy = env->py - env->gems[i].y;
        float dist = sqrtf(dx*dx + dy*dy) + 1e-6f;
        if (dist < env->pickup_range) {
            if (dist > 6.0f) {
                env->gems[i].x += dx / dist * GEM_MAGNET_SPEED;
                env->gems[i].y += dy / dist * GEM_MAGNET_SPEED;
            }
            if (dist < PLAYER_RADIUS + 8.0f) {
                xp_gain += env->gems[i].value;
                env->gems[i].active = 0;
            }
        }
    }
    env->xp += xp_gain;

    for (int i = 0; i < env->n_gems; i++) {
        if (!env->gems[i].active) {
            env->gems[i] = env->gems[env->n_gems - 1];
            env->n_gems--;
            i--;
        }
    }
    return xp_gain;
}

static void apply_upgrade(HoloCure* env) {
    int choice = rand_r(&env->rng) % 7;
    switch (choice) {
        case 0: env->weapon_dmg += 4.0f; break;
        case 1: env->weapon_level = (env->weapon_level < WEAPON_MAX_LEVEL) ? env->weapon_level + 1 : env->weapon_level; break;
        case 2: env->speed += 0.3f; break;
        case 3: env->max_hp += 15.0f; env->hp += 15.0f; if (env->hp > env->max_hp) env->hp = env->max_hp; break;
        case 4: env->pickup_range += 15.0f; break;
        case 5: if (env->proj_count < 5) env->proj_count++; break;
        case 6: env->weapon_level = (env->weapon_level < WEAPON_MAX_LEVEL) ? env->weapon_level + 1 : env->weapon_level; break;
    }
}

static void compute_observations(HoloCure* env) {
    float* obs = env->observations;
    int idx = 0;

    obs[idx++] = env->hp / env->max_hp;
    obs[idx++] = env->px / MAP_W * 2.0f - 1.0f;
    obs[idx++] = env->py / MAP_H * 2.0f - 1.0f;
    obs[idx++] = env->speed / (PLAYER_BASE_SPEED * 3.0f);
    obs[idx++] = (float)env->level / MAX_LEVEL;
    obs[idx++] = (float)env->xp / (env->xp_needed > 0 ? env->xp_needed : 1);
    obs[idx++] = 1.0f - (float)env->step_count / MAX_STEPS;
    obs[idx++] = (float)env->invuln / INVULN_FRAMES;

    for (int i = idx; i < 8 + N_NEAREST_ENEMIES * 4; i++) obs[i] = 0.0f;

    float dists[MAX_ENEMIES];
    int indices[MAX_ENEMIES];
    int n_valid = 0;
    for (int i = 0; i < env->n_enemies; i++) {
        if (!env->enemies[i].active) continue;
        float dx = env->enemies[i].x - env->px;
        float dy = env->enemies[i].y - env->py;
        dists[n_valid] = sqrtf(dx*dx + dy*dy);
        indices[n_valid] = i;
        n_valid++;
    }

    for (int s = 0; s < n_valid - 1; s++) {
        for (int t = s + 1; t < n_valid; t++) {
            if (dists[t] < dists[s]) {
                float td = dists[t]; dists[t] = dists[s]; dists[s] = td;
                int ti = indices[t]; indices[t] = indices[s]; indices[s] = ti;
            }
        }
    }

    idx = 8;
    for (int i = 0; i < N_NEAREST_ENEMIES && i < n_valid; i++) {
        int ei = indices[i];
        float dx = env->enemies[ei].x - env->px;
        float dy = env->enemies[ei].y - env->py;
        float d = dists[i];
        obs[idx++] = (dx > OBS_RANGE ? OBS_RANGE : (dx < -OBS_RANGE ? -OBS_RANGE : dx)) / OBS_RANGE;
        obs[idx++] = (dy > OBS_RANGE ? OBS_RANGE : (dy < -OBS_RANGE ? -OBS_RANGE : dy)) / OBS_RANGE;
        obs[idx++] = (d > OBS_RANGE ? 1.0f : d / OBS_RANGE);
        obs[idx++] = env->enemies[ei].hp / (env->enemies[ei].max_hp > 0 ? env->enemies[ei].max_hp : 1.0f);
    }

    for (int i = idx; i < 8 + N_NEAREST_ENEMIES * 4; i++) obs[i] = 0.0f;
    idx = 8 + N_NEAREST_ENEMIES * 4;

    float gdists[MAX_GEMS];
    int gindices[MAX_GEMS];
    int n_gvalid = 0;
    for (int i = 0; i < env->n_gems; i++) {
        if (!env->gems[i].active) continue;
        float dx = env->gems[i].x - env->px;
        float dy = env->gems[i].y - env->py;
        gdists[n_gvalid] = sqrtf(dx*dx + dy*dy);
        gindices[n_gvalid] = i;
        n_gvalid++;
    }

    for (int s = 0; s < n_gvalid - 1; s++) {
        for (int t = s + 1; t < n_gvalid; t++) {
            if (gdists[t] < gdists[s]) {
                float td = gdists[t]; gdists[t] = gdists[s]; gdists[s] = td;
                int ti = gindices[t]; gindices[t] = gindices[s]; gindices[s] = ti;
            }
        }
    }

    for (int i = 0; i < N_NEAREST_GEMS && i < n_gvalid; i++) {
        int gi = gindices[i];
        float dx = env->gems[gi].x - env->px;
        float dy = env->gems[gi].y - env->py;
        float d = gdists[i];
        obs[idx++] = (dx > OBS_RANGE ? OBS_RANGE : (dx < -OBS_RANGE ? -OBS_RANGE : dx)) / OBS_RANGE;
        obs[idx++] = (dy > OBS_RANGE ? OBS_RANGE : (dy < -OBS_RANGE ? -OBS_RANGE : dy)) / OBS_RANGE;
        obs[idx++] = (d > OBS_RANGE ? 1.0f : d / OBS_RANGE);
    }

    for (int i = idx; i < 8 + N_NEAREST_ENEMIES * 4 + N_NEAREST_GEMS * 3; i++) obs[i] = 0.0f;
    idx = 8 + N_NEAREST_ENEMIES * 4 + N_NEAREST_GEMS * 3;

    for (int i = 0; i < N_SECTORS; i++) obs[idx + i] = 0.0f;
    for (int i = 0; i < env->n_enemies; i++) {
        if (!env->enemies[i].active) continue;
        float dx = env->enemies[i].x - env->px;
        float dy = env->enemies[i].y - env->py;
        float angle = atan2f(dy, dx);
        int sector = (int)((angle + M_PI) / (2.0f * M_PI) * N_SECTORS) % N_SECTORS;
        if (sector < 0) sector += N_SECTORS;
        obs[idx + sector] += 1.0f / 20.0f;
        if (obs[idx + sector] > 1.0f) obs[idx + sector] = 1.0f;
    }
    idx += N_SECTORS;

    obs[idx++] = (float)env->weapon_level / WEAPON_MAX_LEVEL;
    obs[idx++] = 1.0f - (float)env->weapon_cd / (WEAPON_BASE_CD > 0 ? WEAPON_BASE_CD : 1);
    obs[idx++] = (float)env->proj_count / 5.0f;
    obs[idx++] = (env->weapon_dmg > 100.0f ? 1.0f : env->weapon_dmg / 100.0f);
}

void c_reset(HoloCure* env) {
    env->step_count = 0;
    env->px = MAP_W * 0.5f;
    env->py = MAP_H * 0.5f;
    env->hp = PLAYER_BASE_HP;
    env->max_hp = PLAYER_BASE_HP;
    env->speed = PLAYER_BASE_SPEED;
    env->pickup_range = GEM_PICKUP_RADIUS;
    env->level = 1;
    env->xp = 0;
    env->xp_needed = xp_for_level(1);
    env->invuln = 0;
    env->contact_cd = 0;
    env->kills = 0;
    env->weapon_level = 1;
    env->weapon_cd = 0;
    env->weapon_dmg = WEAPON_BASE_DMG;
    env->proj_count = 1;
    env->alive = 1;
    env->spawn_timer = 0;
    env->n_enemies = 0;
    env->n_gems = 0;
    env->n_projectiles = 0;
    env->screenshot_count = 0;
    memset(env->enemies, 0, sizeof(env->enemies));
    memset(env->gems, 0, sizeof(env->gems));
    memset(env->projectiles, 0, sizeof(env->projectiles));
    compute_observations(env);
}

void c_step(HoloCure* env) {
    env->terminals[0] = 0.0f;
    env->rewards[0] = 0.0f;

    if (!env->alive) { c_reset(env); return; }

    env->step_count++;
    int action = (int)env->actions[0];
    if (action < 0) action = 0;
    if (action > 8) action = 8;

    env->px += MOVE_TABLE[action][0] * env->speed;
    env->py += MOVE_TABLE[action][1] * env->speed;
    if (env->px < 0) env->px = 0;
    if (env->px > MAP_W) env->px = MAP_W;
    if (env->py < 0) env->py = 0;
    if (env->py > MAP_H) env->py = MAP_H;

    maybe_spawn_enemies(env);
    update_enemies(env);

    if (env->weapon_cd > 0) env->weapon_cd--;
    fire_weapon(env);
    update_projectiles(env);

    float dmg = check_contact_damage(env);
    if (dmg > 0.0f) {
        env->hp -= dmg;
        env->invuln = INVULN_FRAMES;
        env->rewards[0] -= 0.5f;
        if (env->hp <= 0.0f) {
            env->hp = 0.0f;
            env->alive = 0;
            env->rewards[0] -= 5.0f;
        }
    }
    if (env->invuln > 0) env->invuln--;
    if (env->contact_cd > 0) env->contact_cd--;

    int xp_gain = update_gems(env);
    env->rewards[0] += 0.05f * (float)xp_gain;

    while (env->xp >= env->xp_needed && env->level < MAX_LEVEL) {
        env->xp -= env->xp_needed;
        env->level++;
        env->xp_needed = xp_for_level(env->level);
        apply_upgrade(env);
        env->rewards[0] += 1.0f;
    }

    if (env->alive) env->rewards[0] += 0.01f;

    int truncated = env->step_count >= MAX_STEPS;
    if (truncated && env->alive) env->rewards[0] += 10.0f;
    if (!env->alive) env->terminals[0] = 1.0f;

    if (truncated || !env->alive) {
        env->log.episode_return += env->rewards[0];
        env->log.episode_length += (float)env->step_count;
        env->log.score += (float)env->step_count;
        env->log.kills += (float)env->kills;
        env->log.level += (float)env->level;
        env->log.n += 1.0f;
    }

    compute_observations(env);
}

void c_render(HoloCure* env) {
    if (!IsWindowReady()) {
        InitWindow(800, 800, "PufferLib HoloCure");
        SetTargetFPS(60);
    }
    if (IsKeyDown(KEY_ESCAPE)) exit(0);

    float sx = 800.0f / MAP_W;
    float sy = 800.0f / MAP_H;

    BeginDrawing();
    ClearBackground((Color){6, 24, 24, 255});

    DrawCircle((int)(env->px * sx), (int)(env->py * sy), PLAYER_RADIUS * sx, (Color){0, 187, 187, 255});

    for (int i = 0; i < env->n_enemies; i++) {
        if (!env->enemies[i].active) continue;
        Color c = (env->enemies[i].type == 1) ? (Color){187, 0, 0, 255} :
                  (env->enemies[i].type == 2) ? (Color){100, 100, 100, 255} :
                  (Color){187, 100, 0, 255};
        DrawCircle((int)(env->enemies[i].x * sx), (int)(env->enemies[i].y * sy), 8.0f * sx, c);
    }

    for (int i = 0; i < env->n_gems; i++) {
        if (!env->gems[i].active) continue;
        DrawRectangle((int)(env->gems[i].x * sx) - 2, (int)(env->gems[i].y * sy) - 2, 4, 4, GREEN);
    }

    for (int i = 0; i < env->n_projectiles; i++) {
        if (!env->projectiles[i].active) continue;
        DrawCircle((int)(env->projectiles[i].x * sx), (int)(env->projectiles[i].y * sy), 3.0f, YELLOW);
    }

    DrawText(TextFormat("HP: %.0f  Lv: %d  Kills: %d  Step: %d",
        env->hp, env->level, env->kills, env->step_count), 10, 10, 20, WHITE);
    EndDrawing();
}

void c_close(HoloCure* env) {
    if (IsWindowReady()) CloseWindow();
}
