#!/usr/bin/env python3
"""
Visual training: trains HoloCure with a LIVE game window.

Unlike headless training (thousands of envs, no graphics), this script runs
a small number of envs and renders env 0 in a raylib window DURING training.
You watch the agent play in real-time and see it improve epoch by epoch —
exactly like those "AI learns to play" YouTube videos.

Usage (from WSL):
    DISPLAY=:0 python train_visual.py
    DISPLAY=:0 python train_visual.py --envs 64 --horizon 128
"""

import sys
import os
import time
import numpy as np
import torch
from collections import defaultdict

# Must set argv before importing pufferlib (it reads sys.argv for config)
sys.argv = ['train_visual']

from pufferlib import _C
import pufferlib.pufferl
from pufferlib.torch_pufferl import (
    PuffeRL,
    load_policy,
    _actions_for_vec_step,
    sample_logits,
    _CudaPtr,
    _cpu_tensor,
    _OBS_DTYPE_MAP,
    compute_puff_advantage,
    Profile,
)
from pufferlib.muon import Muon


def main():
    # ── Parse args ────────────────────────────────────────────────────
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--envs', type=int, default=16, help='Number of parallel envs')
    parser.add_argument('--env-name', type=str, default='holocure',
                        choices=['holocure', 'holocure_melee'],
                        help='Environment to train')
    parser.add_argument('--horizon', type=int, default=128, help='Steps per rollout')
    parser.add_argument('--total-timesteps', type=int, default=50_000_000)
    parser.add_argument('--learning-rate', type=float, default=0.003)
    parser.add_argument('--hidden-size', type=int, default=256)
    parser.add_argument('--num-layers', type=int, default=2)
    parser.add_argument('--render-every', type=int, default=1,
                        help='Render every N steps (1=every step, 4=every 4th)')
    args_cli = parser.parse_args()
    # Remove our CLI args so pufferlib doesn't choke on them
    sys.argv = ['train_visual']

    env_name = args_cli.env_name

    # ── Load PufferLib config ──────────────────────────────────────────
    config = pufferlib.pufferl.load_config(env_name)
    config['vec']['total_agents'] = args_cli.envs
    config['vec']['num_buffers'] = 1
    config['vec']['num_threads'] = 1
    config['train']['total_timesteps'] = args_cli.total_timesteps
    config['train']['horizon'] = args_cli.horizon
    config['train']['learning_rate'] = args_cli.learning_rate
    config['train']['minibatch_size'] = max(256, args_cli.envs * args_cli.horizon // 4)
    config['policy']['hidden_size'] = args_cli.hidden_size
    config['policy']['num_layers'] = args_cli.num_layers
    pufferlib.pufferl.validate_config(config)

    # ── Create vecenv + policy ────────────────────────────────────────
    vec = _C.create_vec(config, _C.gpu)
    policy = load_policy(config, vec)
    device = 'cuda' if _C.gpu else 'cpu'

    horizon = config['train']['horizon']
    total_agents = vec.total_agents
    obs_size = vec.obs_size
    num_atns = vec.num_atns
    obs_dtype = _OBS_DTYPE_MAP.get(vec.obs_dtype, torch.uint8)

    # ── Observation / reward / terminal tensor views ───────────────────
    if _C.gpu:
        vec_obs = torch.as_tensor(
            _CudaPtr(vec.gpu_obs_ptr, (total_agents, obs_size), obs_dtype))
        vec_rewards = torch.as_tensor(
            _CudaPtr(vec.gpu_rewards_ptr, (total_agents,), torch.float32))
        vec_terminals = torch.as_tensor(
            _CudaPtr(vec.gpu_terminals_ptr, (total_agents,), torch.float32))
    else:
        vec_obs = _cpu_tensor(vec.obs_ptr, (total_agents, obs_size), obs_dtype)
        vec_rewards = _cpu_tensor(vec.rewards_ptr, (total_agents,), torch.float32)
        vec_terminals = _cpu_tensor(vec.terminals_ptr, (total_agents,), torch.float32)

    # ── Rollout buffers ────────────────────────────────────────────────
    observations = torch.zeros(horizon, total_agents, obs_size,
                               dtype=obs_dtype, device=device)
    actions_buf = torch.zeros(horizon, total_agents, num_atns, device=device)
    values_buf = torch.zeros(horizon, total_agents, device=device)
    logprobs_buf = torch.zeros(horizon, total_agents, device=device)
    rewards_buf = torch.zeros(horizon, total_agents, device=device)
    terminals_buf = torch.zeros(horizon, total_agents, device=device)
    ratio = torch.ones(total_agents, horizon, device=device)
    state = policy.initial_state(total_agents, device=device)

    # ── Optimizer ──────────────────────────────────────────────────────
    optimizer = Muon(policy.parameters(),
                     lr=config['train']['learning_rate'],
                     momentum=config['train']['beta1'],
                     eps=config['train']['eps'])

    batch_size = total_agents * horizon
    total_epochs = max(1, config['train']['total_timesteps'] // batch_size)
    minibatch_segments = config['train']['minibatch_size'] // horizon

    vec.reset()

    global_step = 0
    epoch = 0
    model_size = sum(p.numel() for p in policy.parameters() if p.requires_grad)

    print()
    print('=' * 60)
    print(f'  HoloCure Visual Training [{env_name}] — LIVE game window')
    print(f'  Envs: {total_agents}  Horizon: {horizon}  Batch: {batch_size}')
    print(f'  Policy params: {model_size:,}  Device: {device}')
    print(f'  Total epochs: {total_epochs:,}')
    print(f'  Rendering env 0 every {args_cli.render_every} step(s)')
    print('=' * 60)
    print()

    t0 = time.time()
    best_score = 0.0

    while global_step < config['train']['total_timesteps']:
        # ╔═══════════════════════════════════════════════════════════════╗
        # ║  ROLLOUT — step envs AND render env 0 in real-time          ║
        # ╚═══════════════════════════════════════════════════════════════╝
        state = tuple(torch.zeros_like(s) for s in state) if state else ()
        o = vec_obs
        r = torch.zeros(total_agents, device=device)
        d = torch.zeros(total_agents, device=device)

        for t in range(horizon):
            o_device = torch.as_tensor(o, device=device)

            with torch.no_grad():
                logits, value, state = policy.forward_eval(o_device, state)
                action, logprob, _ = sample_logits(logits)

            with torch.no_grad():
                observations[t] = o_device
                actions_buf[t] = action
                logprobs_buf[t] = logprob
                rewards_buf[t] = torch.as_tensor(r, device=device)
                terminals_buf[t] = torch.as_tensor(d, device=device).float()
                values_buf[t] = value.flatten()

            # Step ALL envs
            actions_flat = _actions_for_vec_step(action)
            if _C.gpu:
                actions_flat = actions_flat.cuda()
                vec.gpu_step(actions_flat.data_ptr())
                torch.cuda.synchronize()
            else:
                vec.cpu_step(actions_flat.data_ptr())

            o, r, d = vec_obs, vec_rewards, vec_terminals

            # ═══════════════════════════════════════════════════════════════
            # RENDER env 0 — this is the key line that makes the window appear
            # ═══════════════════════════════════════════════════════════════
            if t % args_cli.render_every == 0:
                vec.render(0)

        global_step += batch_size
        env_logs = vec.log()

        # ╔═══════════════════════════════════════════════════════════════╗
        # ║  PPO UPDATE                                                   ║
        # ╚═══════════════════════════════════════════════════════════════╝
        losses = defaultdict(float)
        cfg = config['train']

        b0 = cfg['prio_beta0']
        a = cfg['prio_alpha']
        clip_coef = cfg['clip_coef']
        vf_clip = cfg['vf_clip_coef']
        anneal_beta = b0 + (1 - b0) * a * epoch / total_epochs
        ratio[:] = 1

        learning_rate = cfg['learning_rate']
        if cfg['anneal_lr'] and epoch > 0:
            lr_ratio = epoch / total_epochs
            lr_min = cfg['learning_rate'] * cfg['min_lr_ratio']
            learning_rate = lr_min + 0.5 * (learning_rate - lr_min) * (1 + np.cos(np.pi * lr_ratio))
            optimizer.param_groups[0]['lr'] = learning_rate

        obs = observations.transpose(0, 1).contiguous()
        act = actions_buf.transpose(0, 1).contiguous()
        val = values_buf.T.contiguous()
        lp = logprobs_buf.T.contiguous()
        rew = rewards_buf.T.contiguous().clamp(-1, 1)
        ter = terminals_buf.T.contiguous()

        num_minibatches = max(1, int(cfg['replay_ratio'] * batch_size / cfg['minibatch_size']))

        for mb in range(num_minibatches):
            shape = val.shape
            advantages = torch.zeros(shape, device=device)
            advantages = compute_puff_advantage(
                val, rew, ter, ratio, advantages,
                cfg['gamma'], cfg['gae_lambda'],
                cfg['vtrace_rho_clip'], cfg['vtrace_c_clip'])

            adv = advantages.abs().sum(axis=1)
            prio_weights = torch.nan_to_num(adv ** a, 0, 0, 0)
            prio_probs = (prio_weights + 1e-6) / (prio_weights.sum() + 1e-6)
            idx = torch.multinomial(prio_probs, minibatch_segments, replacement=True)
            mb_prio = (total_agents * prio_probs[idx, None]) ** -anneal_beta

            mb_obs = obs[idx]
            mb_actions = act[idx]
            mb_logprobs = lp[idx]
            mb_values = val[idx]
            mb_returns = advantages[idx] + mb_values
            mb_advantages = advantages[idx]

            logits, newvalue = policy(mb_obs)
            _, newlogprob, entropy = sample_logits(logits, action=mb_actions)

            newlogprob = newlogprob.reshape(mb_logprobs.shape)
            logratio = newlogprob - mb_logprobs
            ratio_mb = logratio.exp()
            ratio[idx] = ratio_mb.detach()

            with torch.no_grad():
                approx_kl = ((ratio_mb - 1) - logratio).mean()
                clipfrac = ((ratio_mb - 1.0).abs() > clip_coef).float().mean()

            adv_norm = mb_prio * (mb_advantages - mb_advantages.mean()) / (mb_advantages.std() + 1e-8)

            pg1 = -adv_norm * ratio_mb
            pg2 = -adv_norm * torch.clamp(ratio_mb, 1 - clip_coef, 1 + clip_coef)
            pg_loss = torch.max(pg1, pg2).mean()

            newvalue = newvalue.view(mb_returns.shape)
            v_clipped = mb_values + torch.clamp(newvalue - mb_values, -vf_clip, vf_clip)
            v_loss_unclipped = (newvalue - mb_returns) ** 2
            v_loss_clipped = (v_clipped - mb_returns) ** 2
            v_loss = 0.5 * torch.max(v_loss_unclipped, v_loss_clipped).mean()

            entropy_loss = entropy.mean()
            loss = pg_loss + cfg['vf_coef'] * v_loss - cfg['ent_coef'] * entropy_loss

            val[idx] = newvalue.detach().float()

            losses['policy'] += pg_loss.item()
            losses['value'] += v_loss.item()
            losses['entropy'] += entropy_loss.item()
            losses['kl'] += approx_kl.item()
            losses['clipfrac'] += clipfrac.item()

            loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), cfg['max_grad_norm'])
            optimizer.step()
            optimizer.zero_grad()

        for k in losses:
            losses[k] /= num_minibatches

        epoch += 1
        elapsed = time.time() - t0
        sps = global_step / max(elapsed, 1e-6)

        score = env_logs.get('score', 0)
        ep_ret = env_logs.get('episode_return', 0)
        ep_len = env_logs.get('episode_length', 0)
        kills = env_logs.get('kills', 0)
        level = env_logs.get('level', 0)

        if score > best_score:
            best_score = score

        # Print progress to terminal (the game window shows the visual)
        if epoch % 1 == 0:
            print(
                f'\r  epoch {epoch:5d}/{total_epochs}  '
                f'step {global_step:>12,}  '
                f'SPS {sps:>8,.0f}  '
                f'score {score:7.1f} (best {best_score:7.1f})  '
                f'ret {ep_ret:6.1f}  '
                f'len {ep_len:5.0f}  '
                f'kills {kills:4.0f}  '
                f'lvl {level:.1f}  '
                f'pg {losses["policy"]:.3f}  '
                f'v {losses["value"]:.3f}  '
                f'ent {losses["entropy"]:.3f}  '
                f'kl {losses["kl"]:.4f}  '
                f'  {elapsed:.0f}s',
                end='', flush=True,
            )

    print()
    print(f'\nTraining complete! {global_step:,} steps in {time.time()-t0:.1f}s')
    print(f'Best score: {best_score:.1f}')

    # Save final model
    save_path = os.path.join('checkpoints', 'holocure', 'visual_final.pt')
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    torch.save(policy.state_dict(), save_path)
    print(f'Saved: {save_path}')

    vec.close()


if __name__ == '__main__':
    main()
