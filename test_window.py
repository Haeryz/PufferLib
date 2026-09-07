#!/usr/bin/env python3
"""Minimal raylib test — does a window appear?"""
import ctypes
import time

# Load raylib from the compiled .so
try:
    rl = ctypes.CDLL('./raylib-5.5_linux_amd64/lib/libraylib.so')
    print("raylib loaded from local lib")
except:
    try:
        rl = ctypes.CDLL('libraylib.so')
        print("raylib loaded from system")
    except:
        print("Cannot load raylib!")
        exit(1)

# InitWindow(int width, int height, const char *title)
rl.InitWindow(400, 400, b"CAN YOU SEE ME?")
rl.SetTargetFPS(30)

print("Window created! Look for a 400x400 window.")
print("It should show a green background with text.")
print("Waiting 15 seconds...")

for i in range(450):  # 15 seconds at 30fps
    rl.BeginDrawing()
    rl.ClearBackground(ctypes.c_int(0x00FF00FF))  # green
    # DrawText at (10,10), size 20, white
    rl.DrawText(b"IF YOU SEE THIS, WSLg WORKS", 10, 180, 20, ctypes.c_int(0xFFFFFFFF))
    rl.DrawText(b"Count: %d" % i, 10, 210, 20, ctypes.c_int(0xFFFFFFFF))
    rl.EndDrawing()

rl.CloseWindow()
print("Done")
