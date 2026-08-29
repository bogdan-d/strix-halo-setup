# Reclaiming the amdgpu TTM page pool without a reboot (gfx1151)

**TL;DR — after unloading large models, the amdgpu/TTM page pool holds tens of GB of system
RAM that does NOT drain on its own, which can block loading the next big model (looks like you
need a reboot). `sync; echo 3 | sudo tee /proc/sys/vm/drop_caches` drains it cleanly.**

## Symptom

Stop the resident model(s) and `mem_info_gtt_used` drops to near zero, but `free` barely
recovers — tens of GB stay "used" with no process owning them (sum of all process RSS is small).
Re-reading `MemAvailable` shows it flat over time: the pool does **not** self-drain at idle. On a
128GB (≈123 GiB usable) box this can leave a fleet-down with only ~50-62 GiB available, too little
for a ~90-100 GiB model, so it looks like a reboot is required.

## Fix

```bash
sync; echo 3 | sudo tee /proc/sys/vm/drop_caches
```

`drop_caches` value 2/3 runs `drop_slab -> shrink_slab`, which invokes **every** registered
shrinker — including amdgpu/TTM's pool shrinker — and releases the pooled pages. It is the clean,
synchronous version of "the pool releases under allocation pressure," without the load-and-hope
freeze risk.

**Measured (gfx1151, after a fleet-down):** `MemAvailable` 62.8 → 108.9 GiB in one shot,
`mem_info_gtt_used` unchanged (~0), no freeze, no GPU reset.

## Notes
- Root-only (`/proc/sys/vm/drop_caches` is root-write). Safe — it only drops reclaimable memory.
- The pool **re-holds** after each big model unload, so re-run before each subsequent big load.
- Verify headroom before loading: `awk '/MemAvailable/{print $2/1048576" GiB"}' /proc/meminfo`.
- Distinct from the TTM `pages_limit` cap (a guard against over-allocation) — this is about
  reclaiming already-pooled pages between loads.
