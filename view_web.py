#!/usr/bin/env python3
"""
Real-time web viewer for HoloCure — watch the agent play in your browser.
No WSLg window needed. Serves frames via HTTP.

Usage:
    python view_web.py                          # melee, latest checkpoint
    python view_web.py --env-name holocure      # ranged
    python view_web.py --port 8080

Then open http://localhost:8080 in your Windows browser.
"""

import sys
import os
import glob
import argparse
import threading
import http.server
import time

sys.argv = ['view_web']
from pufferlib import _C
import pufferlib.pufferl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-name', type=str, default='holocure_melee',
                        choices=['holocure', 'holocure_melee'])
    parser.add_argument('--load-model-path', type=str, default='latest')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    sys.argv = ['view_web']

    env_name = args.env_name
    config = pufferlib.pufferl.load_config(env_name)
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

    # Enable web mode in C code (overwrites web_frame.png every render)
    os.environ['WEB_MODE'] = '1'

    # Create native pufferl
    pufferl = _C.create_pufferl(config)
    _C.load_weights(pufferl, load_path)
    print(f'Weights loaded. Params: {pufferl.num_params():,}')

    state = {'running': True, 'step': 0}

    # Game loop thread — renders + steps env, C code saves web_frame.png
    def game_loop():
        while state['running']:
            _C.render(pufferl, 0)
            _C.rollouts(pufferl)
            state['step'] += 1
        _C.close(pufferl)

    # HTTP server — serves the latest web_frame.png
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                html = b'''<!DOCTYPE html>
<html><head><title>HoloCure RL Viewer</title>
<style>body{background:#06181b;margin:0;display:flex;flex-direction:column;align-items:center}
img{width:800px;height:800px;image-rendering:pixelated;border:2px solid #0bb}
h2{color:#0bb;font-family:monospace;margin:10px}</style>
<script>function r(){document.getElementById('f').src='/frame?t='+Date.now()}
setInterval(r,80)</script>
</head><body>
<h2>HoloCure Melee - Live (step <span id="s">0</span>)</h2>
<img id="f" src="/frame" onload="r()">
<script>setInterval(function(){fetch('/step').then(r=>r.text()).then(s=>document.getElementById('s').textContent=s)},500)</script>
</body></html>'''
                self.wfile.write(html)
            elif self.path.startswith('/frame'):
                try:
                    with open('web_frame.png', 'rb') as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header('Content-type', 'image/png')
                    self.send_header('Cache-Control', 'no-cache, no-store')
                    self.end_headers()
                    self.wfile.write(data)
                except FileNotFoundError:
                    self.send_response(404)
                    self.end_headers()
            elif self.path == '/step':
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(str(state['step']).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    print(f'\n========================================')
    print(f'  Open this URL in your Windows browser:')
    print(f'  http://localhost:{args.port}')
    print(f'========================================')
    print(f'\nPress Ctrl+C to stop.\n')

    t = threading.Thread(target=game_loop, daemon=True)
    t.start()

    server = http.server.HTTPServer(('0.0.0.0', args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        state['running'] = False
        print('\nStopped.')


if __name__ == '__main__':
    main()
