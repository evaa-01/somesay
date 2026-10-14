# somesay

> [!WARNING]
> **Made with AI.** It has not been reviewed by experienced developers, so expect mistakes.

A static recompilation of an N64 game into a native Windows program, built with
[N64Recomp](https://github.com/N64Recomp/N64Recomp): the game's MIPS code is translated to C ahead of time and compiled
for the PC. Graphics by [RT64](https://github.com/rt64/rt64), runtime by
[N64ModernRuntime](https://github.com/N64Recomp/N64ModernRuntime), launcher and menus by
[RecompFrontend](https://github.com/N64Recomp/RecompFrontend).

This is a hobby and learning project, shared so others can learn from it.

**No game data is included.** This repository contains no ROM and no game code. You need your own legally obtained copy
of the game; it is recognised by its hash.

## Status

Boots past intro screen but stalls at a busy-wait deadlock (thread blocked on unused message queue). Audio event registration verified but its caller is unclear.

## Building from source

1. Windows 10/11 x64, Visual Studio with "Desktop development with C++", Python 3, Git, LLVM/clang.
2. `tools\get_tools.ps1` clones the pinned tool versions into `tools\`.
3. Put your ROM into `rom\` (SHA-1 `75ebbe451906ce68b0dd43eef9ee44416452a4f1`, 12 MB, big-endian `.z64`).
4. Run the pipeline (`scripts\rebuild.ps1`), then build the runtime (`runtime\build.ps1`).

