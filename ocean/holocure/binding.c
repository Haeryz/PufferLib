#include "holocure.h"

#define OBS_SIZE 108
#define NUM_ATNS 1
#define ACT_SIZES {9}
#define OBS_TENSOR_T FloatTensor

#define Env HoloCure
#include "vecenv.h"

void my_init(Env* env, Dict* kwargs) {
    env->num_agents = 1;
    env->save_frames = 0;
    env->screenshot_count = 0;
    DictItem* item = dict_get_unsafe(kwargs, "save_frames");
    if (item) env->save_frames = (int)item->value;
}

void my_log(Log* log, Dict* out) {
    dict_set(out, "score", log->score);
    dict_set(out, "episode_return", log->episode_return);
    dict_set(out, "episode_length", log->episode_length);
    dict_set(out, "kills", log->kills);
    dict_set(out, "level", log->level);
}
