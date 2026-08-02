#!/usr/bin/env bash
# vLLM on Strix Halo (gfx1151) via the lemonade qualified bundle.
# Full rationale and measured throughput: docs/vllm-gfx1151.md
#
# Four rules this script exists to enforce:
#   1. launch through the bundle's own bin/vllm-server, never bin/python3 -m vllm...
#      (the shim sets LD_LIBRARY_PATH, the real amdsmi, the ROCm flash-attn flag,
#      and CC=<bundled clang> — Triton cannot JIT its kernels without that CC,
#      which presents as EngineDeadError and reads like a missing gfx1151 kernel)
#   2. --gpu-memory-utilization is a fraction of TOTAL memory, not free memory,
#      so it must be chosen against what other services already hold.
#   3. hybrid models (Qwen3.6 = GDN linear attention) need one Mamba cache block
#      per decode sequence, so the default max_num_seqs of 1024 fails an assert
#      AFTER a fully successful load. MAX_SEQS caps it.
#   4. --enforce-eager by default: the phase right after that assert is HIP graph
#      capture, which vllm-project#32180 reports hanging the driver on gfx1151,
#      and a driver hang takes every other GPU service down with it. Set
#      EAGER=0 to try graph capture deliberately, not by accident.
set -euo pipefail

BUNDLE="${VLLM_BUNDLE:-/mnt/Sypherin/vllm-lemonade}"
MODEL="${1:-/mnt/Sypherin/models/qwen36-27b-awq}"
NAME="${2:-$(basename "$MODEL")}"
PORT="${PORT:-8107}"
MEM_FRAC="${MEM_FRAC:-0.35}"
MAX_LEN="${MAX_LEN:-16384}"
MAX_SEQS="${MAX_SEQS:-256}"
EAGER="${EAGER:-1}"

[ -x "$BUNDLE/bin/vllm-server" ] || { echo "no vllm-server shim in $BUNDLE/bin" >&2; exit 1; }

# A previous engine survives `pkill -f vllm` because the child is named
# VLLM::EngineCore (uppercase). A leftover holds ~19 GiB and makes the next run
# thrash, so refuse to start rather than compete with it.
# Note the bracketed patterns: an unbracketed `-f vllm` also matches the command
# line of the shell running it, so a careless pkill kills its own caller.
if pgrep -f '[V]LLM::EngineCore' >/dev/null || pgrep -f '[v]llm.entrypoints' >/dev/null; then
    echo "a vLLM engine is still running — kill it and wait for GTT to drop:" >&2
    echo "  pkill -9 -f '[v]llm.entrypoints'; pkill -9 -f '[V]LLM::EngineCore'" >&2
    exit 1
fi

GTT_MIB=$(awk '{print int($1/1048576)}' /sys/class/drm/card1/device/mem_info_gtt_used 2>/dev/null || echo 0)
TOTAL_MIB=$(free -m | awk '/Mem:/{print $2}')
WANT_MIB=$(awk -v t="$TOTAL_MIB" -v f="$MEM_FRAC" 'BEGIN{printf "%d", t*f}')
echo "GTT in use: ${GTT_MIB} MiB | requesting ${WANT_MIB} MiB (${MEM_FRAC} of ${TOTAL_MIB} MiB total)"
if [ $((GTT_MIB + WANT_MIB)) -gt $((TOTAL_MIB * 85 / 100)) ]; then
    echo "WARNING: ${GTT_MIB} already held + ${WANT_MIB} requested exceeds 85% of RAM." >&2
    echo "         Expect thrashing, not a clean OOM. Lower MEM_FRAC or free a service." >&2
fi

cd "$BUNDLE"
# ~/.local/lib/python3.* can hold a CUDA torch that shadows the bundled ROCm one
export PYTHONNOUSERSITE=1
export HIP_VISIBLE_DEVICES=0

ARGS=(
  --model "$MODEL"
  --served-model-name "$NAME"
  --gpu-memory-utilization "$MEM_FRAC"
  --max-model-len "$MAX_LEN"
  --max-num-seqs "$MAX_SEQS"
  --host 127.0.0.1 --port "$PORT"
)
[ "$EAGER" = "1" ] && ARGS+=(--enforce-eager)

echo "starting vLLM: max_num_seqs=${MAX_SEQS} eager=${EAGER} port=${PORT}"
echo "expect ~7 min to first response (weights ~2 min, then warmup + Triton JIT)"
exec ./bin/vllm-server "${ARGS[@]}"
