// PufferLib 4 Python bindings for the HoloCure native environment.
// Build:  bash build.sh holocure --float
// Train:  python -m pufferlib.pufferl train holocure
//
// OBS layout (108 floats): player(8) + attack(4) + enemies(24*4).
// Action: Discrete(9) movement (0=stop..8=down-right). Single agent.
#include "holocure.h"

#define OBS_SIZE (8 + 4 + OBS_ENEMIES * 4)   // 108
#define NUM_ATNS 1
#define ACT_SIZES {9}
#define OBS_TENSOR_T FloatTensor

#define Env HoloCure
#include "vecenv.h"

void my_init(Env* env, Dict* kwargs) {
    env->num_agents = 1;
    env->save_frames = 0;
    DictItem* item = dict_get_unsafe(kwargs, "save_frames");
    if (item != NULL) env->save_frames = (int)item->value;
}

void my_log(Log* log, Dict* out) {
    dict_set(out, "perf", log->perf);
    dict_set(out, "score", log->score);
    dict_set(out, "episode_return", log->episode_return);
    dict_set(out, "episode_length", log->episode_length);
}
