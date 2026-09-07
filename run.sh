#!/bin/bash
# HoloCure RL - PufferLib 4.0 native CUDA training on WSL2
#
# Usage:
#   bash run.sh train            # FAST: headless training (ranged, no window)
#   bash run.sh train-visual      # SLOW: live game window (ranged, watch agent learn)
#   bash run.sh train-melee       # FAST: headless training (melee, no window)
#   bash run.sh train-melee-visual # SLOW: live game window (melee, watch agent learn)
#   bash run.sh eval              # Evaluate ranged model (renders game window)
#   bash run.sh eval-melee        # Evaluate melee model (renders game window)
#   bash run.sh build             # Rebuild C extensions
#   bash run.sh build-melee        # Rebuild melee C extension
#
# Examples:
#   bash run.sh train --train.total-timesteps 10000000
#   bash run.sh train-visual --envs 32 --horizon 128
#   bash run.sh eval --load-model-path latest --render-mode raylib

export PATH=/usr/bin:/bin:/usr/local/bin:/usr/sbin:/sbin:/root/.local/bin
export CUDA_HOME=/usr/local/cuda-12.9
export VIRTUAL_ENV=/root/puffer_venv
export PATH="$VIRTUAL_ENV/bin:$CUDA_HOME/bin:$PATH"
CUDNN_LIB=$VIRTUAL_ENV/lib/python3.12/site-packages/nvidia/cudnn/lib
NCCL_LIB=$VIRTUAL_ENV/lib/python3.12/site-packages/nvidia/nccl/lib
export LD_LIBRARY_PATH="/usr/local/cuda-12.4/targets/x86_64-linux/lib:/usr/lib/wsl/lib:/usr/local/cuda-12.9/lib64:$CUDNN_LIB:$NCCL_LIB:$LD_LIBRARY_PATH"
export CPATH="/usr/local/cuda-12.4/targets/x86_64-linux/include:$CPATH"
export LIBRARY_PATH="/usr/local/cuda-12.4/targets/x86_64-linux/lib:/usr/lib/wsl/lib:$CUDNN_LIB:$NCCL_LIB:$LIBRARY_PATH"

cd /mnt/d/Banger/RL-Learn/PufferLib

MODE=${1:-train}
shift || true

# Obsolete HoloCure implementations were removed for reconstruction from game
# evidence. Do not accidentally execute a previously compiled environment.
if [[ ! -f ocean/holocure/holocure.h ]]; then
    echo "HoloCure environment is being rebuilt from tools/holocure_reference game evidence." >&2
    echo "Training and evaluation are unavailable until the replacement is implemented and verified." >&2
    exit 1
fi

case $MODE in
    build)
        echo "Rebuilding HoloCure (ranged) C extension..."
        sed -i 's/\r$//' build.sh ocean/holocure/*.c ocean/holocure/*.h src/*.cu src/*.cpp src/*.h 2>/dev/null
        bash build.sh holocure --float
        ;;

    build-melee)
        echo "Rebuilding HoloCure (melee) C extension..."
        sed -i 's/\r$//' build.sh ocean/holocure_melee/*.c ocean/holocure_melee/*.h src/*.cu src/*.cpp src/*.h 2>/dev/null
        bash build.sh holocure_melee --float
        ;;

    train)
        echo "============================================================"
        echo "  HoloCure RANGED — fast training (headless, GPU)"
        echo "============================================================"
        python -m pufferlib.pufferl train holocure "$@"
        ;;

    train-visual)
        export DISPLAY=:0
        export LIBGL_ALWAYS_INDIRECT=0
        export MESA_LOADER_DRIVER_OVERRIDE=d3d12
        echo "============================================================"
        echo "  HoloCure RANGED — visual training (live window)"
        echo "============================================================"
        python train_visual.py "$@"
        ;;

    train-melee)
        echo "============================================================"
        echo "  HoloCure MELEE — fast training (headless, GPU)"
        echo "============================================================"
        python -m pufferlib.pufferl train holocure_melee "$@"
        ;;

    train-melee-visual)
        export DISPLAY=:0
        export LIBGL_ALWAYS_INDIRECT=0
        export MESA_LOADER_DRIVER_OVERRIDE=d3d12
        echo "============================================================"
        echo "  HoloCure MELEE — visual training (live window)"
        echo "============================================================"
        python train_visual.py --env-name holocure_melee "$@"
        ;;

    eval)
        export DISPLAY=:0
        export LIBGL_ALWAYS_INDIRECT=0
        export MESA_LOADER_DRIVER_OVERRIDE=d3d12
        echo "Evaluating HoloCure (ranged)..."
        python -m pufferlib.pufferl eval holocure "$@"
        ;;

    eval-melee)
        export DISPLAY=:0
        export LIBGL_ALWAYS_INDIRECT=0
        export MESA_LOADER_DRIVER_OVERRIDE=d3d12
        echo "Evaluating HoloCure (melee)..."
        python -m pufferlib.pufferl eval holocure_melee "$@"
        ;;

    eval-gif)
        echo "Saving gameplay as GIF..."
        python eval_gif.py "$@"
        ;;

    view)
        export DISPLAY=:0
        echo "========================================"
        echo "  Real-time web viewer"
        echo "  Open http://localhost:8080 in your browser"
        echo "========================================"
        python view_web.py "$@"
        ;;

    *)
        echo "Usage: bash run.sh [mode] [args...]"
        echo ""
        echo "  Modes:"
        echo "    build              Rebuild ranged C extension"
        echo "    build-melee         Rebuild melee C extension"
        echo "    train              FAST: ranged, headless, GPU"
        echo "    train-visual        SLOW: ranged, live game window"
        echo "    train-melee         FAST: melee, headless, GPU"
        echo "    train-melee-visual   SLOW: melee, live game window"
        echo "    eval                Evaluate ranged model (game window)"
        echo "    eval-melee          Evaluate melee model (game window)"
        echo ""
        echo "Examples:"
        echo "  bash run.sh train --train.total-timesteps 10000000"
        echo "  bash run.sh train-melee-visual --envs 32 --horizon 128"
        echo "  bash run.sh eval --load-model-path latest --render-mode raylib"
        exit 1
        ;;
esac
