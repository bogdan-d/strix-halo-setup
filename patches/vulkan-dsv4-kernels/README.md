# Vulkan kernels for the DeepSeek-V4 ops

Five compute shaders implementing DeepSeek-V4-Flash's custom GGML operations on the
**Vulkan** backend. As far as I can find, these are the first Vulkan implementations of
these ops — upstream llama.cpp is adding them CPU-only
([PR #23122](https://github.com/ggml-org/llama.cpp/pull/23122)), and the fork they were
written against ships CPU + Metal only.

| patch | op | tests |
|---|---|---|
| 0001 | `GGML_OP_DSV4_FP8_KV_QUANTIZE` | 7 |
| 0002 | `GGML_OP_DSV4_ROPE_TAIL` | 27 |
| 0003 | `GGML_OP_DSV4_HC_EXPAND` | 8 |
| 0004 | `GGML_OP_DSV4_HC_WEIGHTED_SUM` | 8 |
| 0005 | `GGML_OP_DSV4_HC_SPLIT_SINKHORN` | 14 |

1,153 insertions across 8 files: 5 new `.comp` shaders, the `ggml-vulkan.cpp` wiring
(pipeline creation, dispatch, `supports_op` gates), shader-gen registration, and 64
`test-backend-ops` cases.

## Credit

These patches apply on top of **[antirez/llama.cpp-deepseek-v4-flash](https://github.com/antirez/llama.cpp-deepseek-v4-flash)**,
Salvatore Sanfilippo's experimental DeepSeek-V4 fork, which is itself a fork of
**[ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)**. Both are MIT licensed.
All the DeepSeek-V4 architecture work — the model graph, the op definitions, the CPU and
Metal implementations these were ported from — is theirs. Only the Vulkan shaders and
their wiring are mine.

## Apply

```bash
git clone https://github.com/antirez/llama.cpp-deepseek-v4-flash
cd llama.cpp-deepseek-v4-flash
git am /path/to/patches/vulkan-dsv4-kernels/*.patch

cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build -j --target test-backend-ops llama-cli
```

## Verify

```bash
./build/bin/test-backend-ops test -o \
  DSV4_FP8_KV_QUANTIZE,DSV4_ROPE_TAIL,DSV4_HC_EXPAND,DSV4_HC_WEIGHTED_SUM,DSV4_HC_SPLIT_SINKHORN
```

Expect `64/64 tests passed`. Verified on an AMD Radeon 8060S (RADV, gfx1151).

> **Do not use `-o DSV4`.** The filter is an exact op-name match, not a prefix, so it
> reports `0/0 tests passed` and `OK` — a green result having run nothing.

Regression on the same machine: stock `ROPE` 288/288, `ROPE_BACK` 228/228, and 604/604
across the ops whose shared dispatch code these patches touch.

## What they buy

Measured end-to-end on the same fork, same model, same hardware:

| | tokens | GPU |
|---|---|---|
| before (all 5 ops on CPU fallback) | 0 in 30 minutes | 1% |
| after (5 ops on Vulkan) | coherent generation, 12.3 t/s | ~40% |

The CPU fallback for `FP8_KV_QUANTIZE` alone did a 126-iteration brute-force search per
element; the shader computes the same E4M3FN value directly with bit manipulation and
round-to-nearest-even, verified bit-exact against the CPU implementation over an
exhaustive 403.8M-value sweep.

Note this makes the fork *work*; it does not make it faster than mainline llama.cpp,
which reaches comparable speed on this model using composite standard ops.

## Known gaps

- `sinkhorn_iters = 0` is unreachable (asserted in `ggml.c`), so it is untested by
  construction rather than by omission.
- The z-split dispatch path (>262144 rows) is untested — it needs more tokens in one
  ubatch than any real workload produces. Its index math is identical to patch 0001's.
- Permuted source views (`nb[1] < nb[0]`) work by construction since indexing is pure
  stride arithmetic, but no test asserts it.
- Correctness evidence is synthetic-tensor equivalence against the CPU backend, plus the
  end-to-end generation above. No numeric tolerance was relaxed: all 64 cases pass at the
  harness default.
