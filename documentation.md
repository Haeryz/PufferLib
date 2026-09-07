# HoloCure RL — Documentation

Reverse-engineered HoloCure environment for RL training using PufferLib 4.0's native CUDA backend on WSL2.

## Prerequisites

- Windows 10+ with WSL2 (Ubuntu)
- NVIDIA GPU (tested: GTX 1660 Ti 6GB)
- UV package manager (installed in WSL)
- Docker NOT required

## Project Structure

```
PufferLib/
├── ocean/holocure/           # Ranged attack environment (C)
│   ├── holocure.h            #   Game logic + structs + c_reset/c_step/c_rende
│   ├── holocure.c            #   Standalone raylib executable
│   └── binding.c             #   Python bindings (OBS_SIZE=108, 9 actions)
├── ocean/holocure_melee/     # Melee attack environment (C)
│   ├── holocure_melee.h      #   Slash attack game logic
│   ├── holocure_melee.c      #   Standalone raylib executable
│   └── binding.c             #   Python bindings
├── config/
│   ├── holocure.ini          # Ranged training config
│   └── holocure_melee.ini    # Melee training config
├── pufferlib/
│   ├── _C.cpython-312-x86_64-linux-gnu.so   # Compiled CUDA backend
│   ├── pufferl.py            # CLI entry point (train/eval/sweep/match)
│   ├── torch_pufferl.py      # PyTorch backend (--slowly mode)
│   └── models.py             # Policy networks (MLP, MinGRU, LSTM, GRU)
├── train_visual.py           # Visual training script (live game window)
├── run.sh                    # Master command wrappe
└── src/                      # C/CUDA source (pufferlib.cu, vecenv.h, bindings)
```

## One-Time WSL2 Setup

### 1. Install build tools

```bash
wsl -d Ubuntu -- sudo apt-get install -y build-essential clang libomp-dev python3-dev wget curl ccache
```

### 2. Install CUDA toolkit

```bash
wsl -d Ubuntu -- sudo apt-get install -y --no-install-recommends \
    cuda-nvcc-12-9 cuda-cudart-12-4 cuda-cudart-dev-12-4 \
    libcublas-12-4 libcublas-dev-12-4 \
    libcurand-12-4 libcurand-dev-12-4 \
    libcusolver-12-4 libcusolver-dev-12-4
```

### 3. Set up CUDA paths and stubs

```bash
# Link nvcc from 12.9 into 12.4 tree
wsl -d Ubuntu -- sudo ln -sf /usr/local/cuda-12.4 /usr/local/cuda
wsl -d Ubuntu -- sudo mkdir -p /usr/local/cuda-12.4/bin
wsl -d Ubuntu -- sudo cp /usr/local/cuda-12.9/bin/nvcc /usr/local/cuda-12.4/bin/
wsl -d Ubuntu -- sudo cp /usr/local/cuda-12.9/bin/cudafe++ /usr/local/cuda-12.4/bin/
wsl -d Ubuntu -- sudo cp /usr/local/cuda-12.9/bin/ptxas /usr/local/cuda-12.4/bin/
wsl -d Ubuntu -- sudo cp /usr/local/cuda-12.9/bin/fatbinary /usr/local/cuda-12.4/bin/
wsl -d Ubuntu -- sudo cp /usr/local/cuda-12.9/bin/nvlink /usr/local/cuda-12.4/bin/
wsl -d Ubuntu -- sudo cp /usr/local/cuda-12.9/bin/__nvcc_device_query /usr/local/cuda-12.4/bin/
wsl -d Ubuntu -- sudo cp -r /usr/local/cuda-12.9/bin/crt /usr/local/cuda-12.4/bin/
wsl -d Ubuntu -- sudo cp -r /usr/local/cuda-12.9/nvvm /usr/local/cuda-12.4/
wsl -d Ubuntu -- sudo cp -r /usr/local/cuda-12.9/include/crt /usr/local/cuda-12.4/include/
wsl -d Ubuntu -- sudo cp /usr/local/cuda-12.9/include/cuda_fp16.h /usr/local/cuda-12.4/include/
wsl -d Ubuntu -- sudo cp /usr/local/cuda-12.9/include/cuda_bf16.h /usr/local/cuda-12.4/include/
```

### 4. Create NVML + profiler stub headers

```bash
wsl -d Ubuntu -- sudo tee /usr/local/cuda-12.4/include/nvml.h << 'EOF'
#ifndef NVML_H_STUB
#define NVML_H_STUB
typedef int nvmlReturn_t;
typedef void* nvmlDevice_t;
typedef struct { unsigned int gpu; unsigned int memory; } nvmlUtilization_t;
typedef struct { unsigned long long total, used, free; } nvmlMemory_t;
#define NVML_SUCCESS 0
#ifdef __cplusplus
extern "C" {
#endif
nvmlReturn_t nvmlInit(void);
nvmlReturn_t nvmlShutdown(void);
nvmlReturn_t nvmlDeviceGetHandleByIndex(unsigned int, nvmlDevice_t*);
nvmlReturn_t nvmlDeviceGetUtilizationRates(nvmlDevice_t, nvmlUtilization_t*);
nvmlReturn_t nvmlDeviceGetMemoryInfo(nvmlDevice_t, nvmlMemory_t*);
#ifdef __cplusplus
}
#endif
#endif
EOF

wsl -d Ubuntu -- sudo tee /usr/local/cuda-12.4/include/cuda_profiler_api.h << 'EOF'
#ifndef CUDA_PROFILER_API_STUB
#define CUDA_PROFILER_API_STUB
static inline int cudaProfilerStart(void) { return 0; }
static inline int cudaProfilerStop(void) { return 0; }
#endif
EOF

wsl -d Ubuntu -- sudo mkdir -p /usr/local/cuda-12.4/include/nvtx3
wsl -d Ubuntu -- sudo tee /usr/local/cuda-12.4/include/nvtx3/nvToolsExt.h << 'EOF'
#ifndef NVTX_STUB
#define NVTX_STUB
static inline void nvtxRangePushA(const char* msg) { (void)msg; }
static inline void nvtxRangePop(void) {}
#endif
EOF
```

### 5. Install UV + Python dependencies

```bash
# Install UV
wsl -d Ubuntu -- curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv in WSL native filesystem (faster than Windows drive)
wsl -d Ubuntu -- uv venv /root/puffer_venv --python 3.12

# Install packages (ALL managed by UV, no pip)
wsl -d Ubuntu -- uv pip install --python /root/puffer_venv 'numpy<2.0' pybind11
wsl -d Ubuntu -- uv pip install --python /root/puffer_venv torch --index-url https://download.pytorch.org/whl/cu124
wsl -d Ubuntu -- uv pip install --python /root/puffer_venv nvidia-cudnn-cu12 nvidia-nccl-cu12
wsl -d Ubuntu -- uv pip install --python /root/puffer_venv rich rich_argparse gpytorch scikit-learn wandb
```

### 6. Create library symlinks

```bash
CUDNN_LIB=/root/puffer_venv/lib/python3.12/site-packages/nvidia/cudnn/lib
NCCL_LIB=/root/puffer_venv/lib/python3.12/site-packages/nvidia/nccl/lib

wsl -d Ubuntu -- sudo ln -sf $CUDNN_LIB/libcudnn.so.9 $CUDNN_LIB/libcudnn.so
wsl -d Ubuntu -- sudo ln -sf $NCCL_LIB/libnccl.so.2 $NCCL_LIB/libnccl.so
wsl -d Ubuntu -- sudo ln -sf /usr/lib/wsl/lib/libnvidia-ml.so.1 /usr/lib/wsl/lib/libnvidia-ml.so
wsl -d Ubuntu -- echo "/usr/lib/wsl/lib" | sudo tee /etc/ld.so.conf.d/wsl.conf
wsl -d Ubuntu -- sudo ldconfig
```

### 7. Fix line endings

Windows creates CRLF line endings; WSL needs LF. Run before building:

```bash
wsl -d Ubuntu -- sed -i 's/\r$//' \
    /mnt/d/Banger/RL-Learn/PufferLib/build.sh \
    /mnt/d/Banger/RL-Learn/PufferLib/ocean/holocure/*.c \
    /mnt/d/Banger/RL-Learn/PufferLib/ocean/holocure/*.h \
    /mnt/d/Banger/RL-Learn/PufferLib/ocean/holocure_melee/*.c \
    /mnt/d/Banger/RL-Learn/PufferLib/ocean/holocure_melee/*.h \
    /mnt/d/Banger/RL-Learn/PufferLib/src/*.cu \
    /mnt/d/Banger/RL-Learn/PufferLib/src/*.cpp \
    /mnt/d/Banger/RL-Learn/PufferLib/src/*.h \
    /mnt/d/Banger/RL-Learn/PufferLib/run.sh \
    /mnt/d/Banger/RL-Learn/PufferLib/train_visual.py
```

---

## Building

### Build ranged environment

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh build
```

### Build melee environment

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh build-melee
```

> **Note:** Both envs compile to the same `pufferlib/_C.so`. You must rebuild when switching between ranged and melee.

---

## Training

### Ranged — Fast (headless, no game window)

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train
```

With custom args:

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train \
    --vec.total-agents 4096 \
    --train.total-timesteps 10000000 \
    --train.learning-rate 0.003 \
    --policy.hidden-size 256 \
    --policy.num-layers 2
```

### Ranged — Visual (live game window, watch agent learn)

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train-visual
```

With custom args:

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train-visual \
    --envs 32 --horizon 128 --render-every 1
```

### Melee — Fast (headless, no game window)

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train-melee
```

### Melee — Visual (live game window, watch agent learn)

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train-melee-visual
```

---

## Evaluation

### Evaluate ranged agent (renders game window)

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh eval \
    --load-model-path latest \
    --render-mode raylib
```

Load a specific checkpoint:

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh eval \
    --load-model-path checkpoints/holocure/<run_id>/<step>.bin \
    --render-mode raylib
```

### Evaluate melee agent (renders game window)

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh eval-melee \
    --load-model-path latest \
    --render-mode raylib
```

---

## Game Window

WSLg displays the raylib window as a native Windows window. If the window doesn't appear:

1. **Alt-Tab** through open windows — look for "PufferLib HoloCure" or "PufferLib HoloCure Melee"
2. Check the **Windows taskbar** for a new icon
3. Restart WSLg: `wsl --shutdown` then wait 5 seconds and retry
4. Press **ESC** in the game window to quit

---

## Environment Details

### Action Space (both envs)

```
Discrete(9): 0=stop, 1=up, 2=down, 3=left, 4=right,
             5=up-left, 6=up-right, 7=down-left, 8=down-right
```

### Observation Space (both envs)

```
Box(float32, shape=(108,)):
  - 8 player features (hp, position, speed, level, xp, time, invuln)
  - 16 nearest enemies x 4 (dx, dy, dist, hp_ratio)
  - 8 nearest gems x 3 (dx, dy, dist)
  - 8 sector enemy density
  - 4 weapon features (level, cooldown, proj_count/range, damage)
```

### Ranged vs Melee

| Feature         | Ranged                    | Melee                          |
|----------------|---------------------------|--------------------------------|
| Attack         | Projectile toward nearest | Slash all enemies in radius     |
| Range          | Unlimited (projectile)     | 70px circle around player       |
| Damage         | 10/hit, one enemy          | 18/swing, all in range          |
| Cooldown       | 28 frames                 | 22 frames                      |
| HP             | 100                       | 120                            |
| Speed          | 3.2                       | 3.6                            |
| Multi-upgrade  | More projectiles          | Larger melee range             |
| Playstyle      | Kite at range             | Dive into crowds (risk/reward) |

### Reward Structure

| Event              | Reward |
|--------------------|--------|
| Kill enemy          | +1.0   |
| Collect XP gem      | +0.05 per XP |
| Level up            | +1.0   |
| Survive per step    | +0.01  |
| Take damage         | -0.5   |
| Die                | -5.0   |
| Survive full stage  | +10.0  |

### Game Mechanics (reverse-engineered from HoloCure)

- 1600x1600 arena, top-down 2D
- Enemies spawn in rings around player, chase, deal contact damage
- 3 enemy types: normal (orange), fast (red), tank (grey)
- XP gems drop on kill, magnet-pulled within pickup range
- Level up grants random stat upgrade (damage, attack speed, move speed, max HP, pickup range, multi-shot/ melee range)
- Difficulty escalates over time (more spawns, higher HP)
- Episode ends on death or 1200 steps (truncation)

---

## PufferLib CLI (advanced)

### Sweep hyperparameters

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train \
    --sweep.method Protein --sweep.max-runs 100
```

### PyTorch backend (slower, for debugging)

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train --slowly
```

### Using a different policy network

```bash
# MinGRU (recurrent, better for partial observability)
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train \
    --torch.network MinGRU --policy.num-layers 1

# LSTM
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train \
    --torch.network LSTM --policy.num-layers 1
```

---

## Useful PufferLib CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--vec.total-agents` | 4096 | Number of parallel environments |
| `--vec.num-buffers` | 4 | Buffer count for async stepping |
| `--vec.num-threads` | 4 | CPU threads for env stepping |
| `--train.total-timesteps` | 10M | Total training steps |
| `--train.learning-rate` | 0.003 | Learning rate |
| `--train.horizon` | 64 | Steps per rollout |
| `--train.minibatch-size` | 4096 | Minibatch size |
| `--train.gamma` | 0.99 | Discount factor |
| `--train.gae-lambda` | 0.95 | GAE lambda |
| `--train.ent-coef` | 0.01 | Entropy coefficient |
| `--train.clip-coef` | 0.2 | PPO clip coefficient |
| `--policy.hidden-size` | 256 | Network hidden size |
| `--policy.num-layers` | 2 | Network depth |
| `--torch.network` | MLP | Network type (MLP, MinGRU, LSTM, GRU) |
| `--checkpoint-interval` | 500 | Save checkpoint every N epochs |
| `--checkpoint-dir` | checkpoints | Directory for checkpoints |
| `--render-mode` | auto | Render mode (raylib, human, ansi) |
| `--load-model-path` | None | Load checkpoint (or "latest") |
| `--seed` | 73 | Random seed |
| `--cudagraphs` | 10 | Epoch to start CUDA graph capture |

---

## File Locations

| Path | Description |
|------|-------------|
| `checkpoints/holocure/<run_id>/*.bin` | Ranged checkpoints |
| `checkpoints/holocure_melee/<run_id>/*.bin` | Melee checkpoints |
| `logs/holocure/*.json` | Training logs |
| `pufferlib/_C.cpython-312-x86_64-linux-gnu.so` | Compiled CUDA backend |

---

## Troubleshooting

### Build fails: "cannot find -lnvidia-ml"

Recreate the symlinks (WSL restart resets them):

```bash
CUDNN_LIB=/root/puffer_venv/lib/python3.12/site-packages/nvidia/cudnn/lib
NCCL_LIB=/root/puffer_venv/lib/python3.12/site-packages/nvidia/nccl/lib
wsl -d Ubuntu -- sudo ln -sf /usr/lib/wsl/lib/libnvidia-ml.so.1 /usr/lib/wsl/lib/libnvidia-ml.so
wsl -d Ubuntu -- sudo ln -sf $CUDNN_LIB/libcudnn.so.9 $CUDNN_LIB/libcudnn.so
wsl -d Ubuntu -- sudo ln -sf $NCCL_LIB/libnccl.so.2 $NCCL_LIB/libnccl.so
```

### Build fails: "set: -: invalid option" or "$'\r': command not found"

Windows line endings in build.sh. Fix with:

```bash
wsl -d Ubuntu -- sed -i 's/\r$//' /mnt/d/Banger/RL-Learn/PufferLib/build.sh
wsl -d Ubuntu -- sed -i 's/\r$//' /mnt/d/Banger/RL-Learn/PufferLib/ocean/holocure/*.c /mnt/d/Banger/RL-Learn/PufferLib/ocean/holocure/*.h
wsl -d Ubuntu -- sed -i 's/\r$//' /mnt/d/Banger/RL-Learn/PufferLib/ocean/holocure_melee/*.c /mnt/d/Banger/RL-Learn/PufferLib/ocean/holocure_melee/*.h
wsl -d Ubuntu -- sed -i 's/\r$//' /mnt/d/Banger/RL-Learn/PufferLib/src/*.cu /mnt/d/Banger/RL-Learn/PufferLib/src/*.cpp /mnt/d/Banger/RL-Learn/PufferLib/src/*.h
```

### Game window not visible

```bash
wsl --shutdown
# Wait 5 seconds, then retry
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh train-visual
```

### numpy import error (numpy 2.x conflict)

```bash
wsl -d Ubuntu -- uv pip install --python /root/puffer_venv 'numpy<2.0' --reinstall
```

### torch has no CUDA

```bash
wsl -d Ubuntu -- uv pip install --python /root/puffer_venv torch --index-url https://download.pytorch.org/whl/cu124 --reinstall
```

### "env_name mismatch" erro

You built for one env but trying to run the other. Rebuild:

```bash
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh build         # ranged
wsl -d Ubuntu -- bash /mnt/d/Banger/RL-Learn/PufferLib/run.sh build-melee    # melee
```

---

## Verify Setup

```bash
# Check CUDA
wsl -d Ubuntu -- /usr/lib/wsl/lib/nvidia-smi

# Check Python + PyTorch
wsl -d Ubuntu -- /root/puffer_venv/bin/python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# Check _C import
wsl -d Ubuntu -- /root/puffer_venv/bin/python -c "from pufferlib import _C; print('env:', _C.env_name, 'gpu:', _C.gpu)"
```
