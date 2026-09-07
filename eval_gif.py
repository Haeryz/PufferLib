#!/usr/bin/env python3
"""
Save HoloCure gameplay as a GIF — no game window needed.
Uses PufferLib's native CUDA backend to load .bin checkpoints and render.

Usage:
    python eval_gif.py                                  # melee, latest checkpoint
    python eval_gif.py --env-name holocure               # ranged
    python eval_gif.py --frames 600 --fps 30             # more frames

Output: eval.gif (open in Windows)
"""

import sys
import os
import glob
import argparse
import time

sys.argv = ['eval_gif']
from pufferlib import _C
import pufferlib.pufferl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-name', type=str, default='holocure_melee',
                        choices=['holocure', 'holocure_melee'])
    parser.add_argument('--load-model-path', type=str, default='latest')
    parser.add_argument('--frames', type=int, default=300,
                        help='Number of rollout steps (each = horizon env steps)')
    parser.add_argument('--output', type=str, default='eval.gif')
    parser.add_argument('--fps', type=int, default=15)
    args = parser.parse_args()
    sys.argv = ['eval_gif']

    env_name = args.env_name
    config = pufferlib.pufferl.load_config(env_name)
    config['env']['save_frames'] = 1
    config['vec']['total_agents'] = 1
    config['vec']['num_buffers'] = 1
    config['vec']['num_threads'] = 1
    config['train']['horizon'] = 1

    # Resolve checkpoint
    load_path = args.load_model_path
    if load_path == 'latest':
        pattern = os.path.join(config['checkpoint_dir'], env_name, '**', '*.bin')
        candidates = glob.glob(pattern, recursive=True)
        if not candidates:
            print(f'No checkpoints found in {config["checkpoint_dir"]}/{env_name}/')
            return
        load_path = max(candidates, key=os.path.getctime)
    print(f'Loading: {load_path}')

    # Clean up old frames
    for f in glob.glob('frame_*.png'):
        os.remove(f)

    # Set env var so C code saves screenshots (more reliable than config)
    os.environ['SAVE_FRAMES'] = '1'

    # Create native pufferl (loads .bin correctly)
    print('Creating native backend pufferl...')
    pufferl = _C.create_pufferl(config)
    _C.load_weights(pufferl, load_path)
    print(f'Weights loaded. Params: {pufferl.num_params():,}')

    print(f'Running {args.frames} rollout steps (rendering + saving frames)...')
    print(f'  A raylib window may open — frames also save to eval_frames/')

    for step in range(args.frames):
        _C.render(pufferl, 0)
        _C.rollouts(pufferl)
        if step % 20 == 0:
            print(f'  step {step}/{args.frames}')

    _C.close(pufferl)

    # Combine PNGs into GIF
    frames = sorted(glob.glob('frame_*.png'))
    print(f'\nCaptured {len(frames)} PNG frames')
    if not frames:
        print('No frames captured — check that raylib is rendering')
        return

    print(f'Combining into {args.output}...')
    try:
        from PIL import Image
        imgs = [Image.open(f) for f in frames]
        imgs[0].save(
            args.output,
            save_all=True,
            append_images=imgs[1:],
            duration=1000 // args.fps,
            loop=0,
        )
        print(f'Saved: {args.output} ({len(imgs)} frames at {args.fps} fps)')
    except ImportError:
        print('Pillow not installed. PNG frames are in eval_frames/')
        return

    # Clean up PNGs
    for f in frames:
        os.remove(f)
    print('Cleaned up PNGs. Done!')


if __name__ == '__main__':
    main()
