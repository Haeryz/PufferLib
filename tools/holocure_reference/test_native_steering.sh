#!/bin/bash
# Diagnostic C transitions only. This does not launch training.
set -eu
cd "$(dirname "$0")/../.."
mkdir -p build/holocure_reference
for mode in standard melee; do
    flags=()
    if [ "$mode" = melee ]; then flags+=(-DTEST_MELEE); fi
    gcc -O2 -ffunction-sections -fdata-sections "${flags[@]}" \
        -Iraylib-5.5_linux_amd64/include \
        tools/holocure_reference/test_native_steering.c \
        -Wl,--gc-sections -lm -o "build/holocure_reference/steering_$mode"
    "build/holocure_reference/steering_$mode"
done
