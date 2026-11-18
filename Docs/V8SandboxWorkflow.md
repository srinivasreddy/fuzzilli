# V8 heap-sandbox fuzzing workflow

This document covers SbxBrk-style testing of V8’s heap sandbox: an attacker is
assumed to have arbitrary read/write access **inside** the sandbox and attempts
to corrupt trusted data outside it. Fuzzilli provides two complementary modes:

- **`v8Sandbox`** — the Memory-Corruption-API baseline (FuzzilliSbx in the
  SbxBrk paper): a post-processor traverses sandbox objects and mutates fields,
  optionally with a background worker for double-fetch/TOCTOU shapes.
- **`v8SandboxTrap`** — V8’s trap-based sandbox fuzzer: memory-protection keys
  trap sandbox accesses and V8 mutates data at the faulting load. This is the
  closest built-in equivalent to SbxBrk’s load-level fault injection.

The general VRP campaign/triage workflow is in
[V8VRPWorkflow.md](V8VRPWorkflow.md).

## 1. Build the sandbox target

The two modes need different build flags.

### Memory-Corruption-API baseline

```bash
cd /path/to/v8
gn gen out/sandbox --args='is_debug=false dcheck_always_on=false \
  v8_enable_sandbox=true v8_enable_memory_corruption_api=true \
  v8_enable_partition_alloc=false v8_fuzzilli=true \
  sanitizer_coverage_flags="trace-pc-guard" target_cpu="x64"'
ninja -C out/sandbox d8
```

### Trap-based load fault injection

```bash
gn gen out/sandbox-trap --args='is_debug=false dcheck_always_on=false \
  v8_enable_sandbox=true v8_enable_memory_corruption_api=true \
  v8_enable_sandbox_hardware_support=true \
  v8_enable_partition_alloc=false v8_fuzzilli=true \
  sanitizer_coverage_flags="trace-pc-guard" target_cpu="x64"'
ninja -C out/sandbox-trap d8
```

The trap fuzzer requires x86-64 memory protection keys (`pku`/`ospke`). If the
host kernel/CPU does not expose them, `mksnapshot` with
`v8_enable_sandbox_hardware_support=true` fails with SIGILL; use the
`v8Sandbox` Memory-Corruption-API baseline on that host (or a pkey-capable
Linux/x64 machine). The trap fuzzer also requires `--single-threaded`; use
multiple Fuzzilli jobs for parallelism.

Build Fuzzilli:

```bash
cd /path/to/fuzzilli
swift build -c release --product FuzzilliCli
```

## 2. Run campaigns

API baseline (deterministic-ish, worker-enabled):

```bash
Tools/v8-vrp-campaign.sh \
  --d8 /path/to/v8/out/sandbox/d8 \
  --profiles v8Sandbox \
  --jobs 8 --duration 2h \
  --out /tmp/v8-sandbox
```

Trap-based load injection:

```bash
Tools/v8-vrp-campaign.sh \
  --d8 /path/to/v8/out/sandbox-trap/d8 \
  --profiles v8SandboxTrap \
  --jobs 8 --duration 2h \
  --out /tmp/v8-sandbox-trap
```

Use `--resume` on subsequent runs. The campaign keeps logs, metadata, crashes,
statistics, and a summary. The trap fuzzer prints its initialization interval
and warnings; crashes are generally **not reproducible**, so keep the logs.

## 3. Triage

```bash
Tools/v8-vrp-triage.py \
  /tmp/v8-sandbox-trap/storage/v8SandboxTrap \
  --d8 /path/to/v8/out/sandbox-trap/d8 \
  --asan-d8 /path/to/v8/out/sandbox-trap-asan/d8 \
  --out /tmp/v8-sandbox-trap/triage
```

For trap-based findings:
- Expect flaky/non-deterministic reproductions; the report marks them.
- Reconstruct the mutation from the campaign log if needed.
- Confirm the crash is a **sandbox escape** (memory outside the sandbox), not an
  OOB read or a non-security assertion.
- Run with the sandbox crash filter (`--sandbox-fuzzing`) and ASan.
- Do **not** report `v8MaglevFaultInjection` or other injected-fault canaries.

For the API baseline, the same triage flow applies and findings are usually
reproducible.

## 4. What to target

The sandbox attack surface is trusted code consuming sandbox data. Focus on:

- element-kind/length fields used for allocation or `std::sort`/`memcpy` sizes;
- typed-array byte lengths and backing-store metadata;
- string lengths and external/wrapper pointers;
- enum discriminants stored on-heap (non-exhaustive switches);
- lookup-table indices and pointer-table metadata;
- double-fetches of lengths/pointers;
- Worker/TOCTOU races against `Sandbox.MemoryView` mutations.

## 5. SbxBrk mapping and limitations

| SbxBrk concept | Fuzzilli/V8 equivalent |
|---|---|
| Attacker controls sandbox memory | `Sandbox.MemoryView` / Memory Corruption API |
| Inject faults at loads crossing the boundary | `v8SandboxTrap` (`--sandbox-trap-fuzzing`) |
| Coverage-guided fault masks | Fuzzilli coverage + V8 trap mutations |
| JS seed corpus | Fuzzilli corpus/`--importCorpus` |
| Double-fetch/TOCTOU | `v8Sandbox`’s worker corruption helpers |
| SbxBrk LLVM/assembler instrumentation | V8 trap fuzzer (built-in pkey traps) |

Limitations:
- The trap fuzzer is not input-mask-controlled and its crashes are timing
  dependent; use logs and repeated campaigns.
- `v8Sandbox` API corruption is not load-level; it mutates object fields before
  later loads.
- The trap fuzzer requires hardware support and `--single-threaded`; Workers are
  not available in that profile.
- ASan builds and the sandbox crash filter are required for reliable severity
  assessment.

## 6. Reporting

Report a candidate only if it corrupts trusted memory outside the sandbox. Include
the V8 revision, sandbox build flags (`v8_enable_sandbox`,
`v8_enable_sandbox_hardware_support`, ASan), the JS reproducer (or trap log),
and the observed out-of-sandbox access. Use the Chrome VRP process described in
[V8VRPWorkflow.md](V8VRPWorkflow.md).
