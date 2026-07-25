# Fine-tuning on Strix Halo: Unsloth on ROCm (gfx1151)

Verified on a Ryzen AI Max / Strix Halo box, 128 GB unified memory, Fedora 43.
Everything below was run on the machine, not read from docs.

## Install

Unsloth shipped official AMD/ROCm support on 2026-07-20 (v0.1.50-beta); gfx1151 is
explicitly supported. Install into an isolated prefix rather than the system Python:

```bash
curl -fsSL https://unsloth.ai/install.sh -o install.sh
# read it first: it is AGPL, self-contained, and its apt/sudo path is Debian-only
UNSLOTH_PYTHON=3.12 UNSLOTH_SKIP_AUTOSTART=1 NO_COLOR=1 sh install.sh
```

- `UNSLOTH_PYTHON=3.12` matters. Fedora 43 ships Python 3.14, which is too new for the
  ROCm torch wheels; the installer builds its own uv venv at `~/.unsloth/studio/`.
- `UNSLOTH_SKIP_AUTOSTART=1` keeps it from launching a server at install time and
  competing with anything already holding the GPU.
- Footprint is about 9.4 GB.

For scripted training, call the venv interpreter directly instead of activating:

```bash
~/.unsloth/studio/unsloth_studio/bin/python train.py
```

## Verified stack

| Component | Version |
|---|---|
| torch | 2.11.0+rocm7.13.0 |
| HIP | 7.13.99004 |
| system ROCm | 7.2.1 |
| transformers | 5.14.1 |
| peft | 0.18.1 |
| unsloth | 2026.7.4 |
| device 0 | Radeon 8060S Graphics (gfx1151) |

`torch.cuda.is_available()` is `True` and `import unsloth` succeeds on this stack.

## Three caveats

1. **Default Studio port is 8888**, which collides with plenty of self-hosted tooling.
   Launch with `unsloth studio -p 8899` if 8888 is taken.
2. **No flash-attn wheel for gfx1151.** It is optional; training runs on the prebuilt
   ROCm kernels without it. Don't waste an afternoon compiling it.
3. **`Python.h` missing** makes a small `hip_utils.c` JIT helper fail to compile at
   import. Non-fatal - import and training both work, a compiled fast path is skipped.
   Install the dev headers for the venv's Python 3.12 if you care about the last few
   percent.

## LoRA on a multimodal base (Gemma 4 E4B)

This is the part that costs a day if you discover it the hard way. Gemma 4's vision and
audio towers wrap their projections in `Gemma4ClippableLinear`, which peft cannot inject
into. Unsloth's fast path also could not load this base for training. Two consequences:

**Scope `target_modules` to the text backbone by regex:**

```python
LoraConfig(
    r=16, lora_alpha=16, lora_dropout=0.0, bias="none", task_type="CAUSAL_LM",
    target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$",
)
```

**Skip TRL's multimodal collator.** A plain `transformers.Trainer` with
`DataCollatorForSeq2Seq` over text-only inputs trains fine:

```python
model = getattr(transformers, "AutoModelForImageTextToText").from_pretrained(
    BASE, torch_dtype=torch.bfloat16, device_map={"": 0})
model.config.use_cache = False
model.enable_input_require_grads()      # required before gradient checkpointing on a PEFT wrap
```

Reference numbers: 156 examples, batch 1, grad-accum 8, 3 epochs, lr 2e-4, bf16,
gradient checkpointing - 60 optimizer steps at ~6.4 s/step, about 6.5 minutes wall.

## Merge and convert

`merge_and_unload()` **does** write back through the `Gemma4ClippableLinear` wrappers.
That was the open question; it works, and returns a `Gemma4ForConditionalGeneration`
you can `save_pretrained()`.

llama.cpp converts the result without special flags:

```bash
python convert_hf_to_gguf.py <merged-dir> --outfile model-Q8_0.gguf.partial --outtype q8_0
```

Its converter registers `Gemma4ForCausalLM`, `Gemma4ForConditionalGeneration`,
`Gemma4AssistantForCausalLM` and `Gemma4UnifiedForConditionalGeneration`. If you read
somewhere that llama.cpp lacks `gemma4` support, check again before believing it - we
published that claim ourselves and it was wrong.

## Unified memory discipline

On Strix Halo the GPU allocates from the same 128 GB as everything else, so a training
or conversion job competes directly with any resident model server. Two freezes in two
days taught us the rules:

1. **Stop the GPU consumers first** - image generation, vision models, anything holding
   GTT - and restore them on exit via a trap, so a failed job doesn't leave them down.
2. **Cap the job.** Run it inside a transient cgroup scope with a hard memory ceiling:
   `systemd-run --user --scope -p MemoryMax=60G -p MemorySwapMax=2G <cmd>`.
3. **Add a sentinel.** Poll `MemAvailable` and SIGKILL the job below a floor (we use
   12 GiB). Killing one job beats losing the desktop.
4. **Write big artifacts to `<out>.partial` and `mv` on success.** A 7.9 GB GGUF write
   that dies at 82% otherwise leaves a truncated file sitting at the real filename,
   looking valid. Ours did.

Point 4 is not theoretical - the write died because the *output* volume filled up while
the OS volume still showed 135 GiB free. Check the filesystem you are actually writing
to, not `$HOME`.
