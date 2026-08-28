# Changelog

## Build history

| Component | Version | Date | Notes |
|-----------|---------|------|-------|
| Qwen3.8-27B VL on :8022 | unsloth UD-Q4_K_XL + mmproj-F16 | 2026-08-14 | Native VL + native MTP in one model; replaced Muse-Glimmer as the second resident |
| Kernel + boot params | 7.2.0-rc3 vanilla; `amd_iommu=off`, TTM cap 108GiB | 2026-08-09 | IOMMU off (5-12% on this platform); TTM capped below GTT so the GPU can't starve the host |
| Muse-Glimmer-30B on :8022 | custom ROCm-FP4 build | 2026-08-08 | Second resident (vision), ~26.5 t/s; retired 08-14, unit kept as rollback |
| llama.cpp | fresh upstream `~/llama.cpp` @ 69bf643 (Vulkan) | 2026-08-08 | Current build for :8001 and :8022 |
| llama.cpp | fresh upstream `~/llama.cpp` @ fb30ba9 (Vulkan) | 2026-07-10 | Native MTP (`--spec-type draft-mtp`), Qwen3.6 primary, ~75–86 t/s tg |
| Qwen3.6-35B-A3B MTP model | unsloth UD-Q4_K_XL (~22.85 GB) | 2026-07-10 | MTP layers grafted into GGUF; 256k ctx |
| llama.cpp | 8793 (Vulkan build from turboquant fork) | 2026-04-03 | 393 t/s pp, 22 t/s tg |
| llama-server | b8461 (kyuz0 Vulkan RADV) | 2026-03 | 351 t/s pp, 19 t/s tg (replaced) |
| llama-server | b8299 (official release) | 2026-03-13 | +40% prompt speed over b8119 |
| llama-server | b8119 (kyuz0 custom) | 2026-02 | Initial build |
| Kernel | 7.1.0-rc4 (vanilla) | 2026-04-04 | +12-37% pp over 6.19.9 |
| Kernel | 6.19.9 (Fedora 43) | 2026-03 | Previous stable |
| XRT | 2.23.0 | 2026-03-22 | Built from amd/xdna-driver submodule |
| amdxdna driver | 2.23.0 (DKMS) | 2026-03-22 | Out-of-tree, replaces kernel v0.6.0 |
| NPU firmware | 1.0.0.166 | 2026-03 | Protocol v6.x |

