# V8 fuzzing experiments and recommendations

This document turns the recommended experiments into a runnable matrix. The
matrix runner starts one `Tools/v8-vrp-campaign.sh` campaign per row and emits a
Markdown/TSV/JSON results table.

## Matrix format

`Tools/v8-fuzzing-matrix.example.tsv` is a tab-separated file:

```
id	profile	d8	asan_d8	jobs	duration	notes
```

- `id` — unique experiment name (also the output subdirectory).
- `profile` — `v8`, `v8Maglev`, `v8Sandbox`, `v8SandboxTrap`,
  `v8MaglevFaultInjection`, etc.
- `d8` — non-ASan target d8.
- `asan_d8` — optional ASan d8; use `-` to disable.
- `jobs` — Fuzzilli jobs.
- `duration` — e.g. `30m`, `8h`, `72h`.
- `notes` — free text shown in the report.

Lines starting with `#` and an `id` header are ignored.

## Run the matrix

```bash
Tools/v8-fuzzing-matrix.py \
  --matrix Tools/v8-fuzzing-matrix.example.tsv \
  --out /tmp/v8-experiments
```

Useful flags:
- `--dry-run` — print commands without starting campaigns.
- `--resume` — resume existing storage (for repeated runs).
- `--continue-on-error` — keep going after a failed row.

Outputs:
- `RESULTS.md` — comparison table.
- `RESULTS.tsv`, `RESULTS.json` — raw results for further analysis.
- `<id>/` — campaign metadata, logs, storage, crashes/differentials.
- `matrix.tsv` — exact matrix used.

## Recommended matrix

Start with a small calibration matrix, then scale up:

1. **v8-baseline** — general crash/assertion hunting on latest main.
2. **maglev-diff** — Maglev vs. `--no-maglev --no-turbofan`, with the
   `v8Maglev` profile.
3. **sandbox-api** — `v8Sandbox` (Memory-Corruption-API + workers). Works
   without pkeys.
4. **sandbox-trap** — `v8SandboxTrap` on a pkey-capable host. Crashes are
   timing-dependent.
5. **fault-canary** — `v8MaglevFaultInjection`; validates the harness, never a
   VRP candidate.

For a first pass on a 4-core/8-thread machine, use 5–15 minutes per row to
verify startup and reporting; then run 24–72 hours per row for real results.

## Interpreting results

- Compare only rows with the same V8 revision and build configuration.
- `Correctness Rate` is not a bug count; low values often reflect generated
  code that throws.
- `Execs / Second` identifies startup or instrumentation problems.
- Trap crashes are non-reproducible; use campaign logs and the crash footer.
- A crash on a **fixed** revision is not a new bug. Recheck candidates on latest
  `origin/main`.
- Fault-injection canaries (`v8MaglevFaultInjection`) must be excluded from VRP
  findings.

## Experiment ideas

### Sandbox
- `v8Sandbox` vs `v8SandboxTrap` on a pkey host.
- ASan vs dcheck vs release.
- Worker/TOCTOU corruption on vs off.
- Sink-focused seeds: typed-array sort, JSON, number/string conversions,
  enum tables, pointer tables.
- Compiler/optimization variation: bugs may only appear at `-O0` or after
  compiler changes.

### Maglev
- Maglev vs no-Maglev vs TurboFan.
- `--maglev-inlining`, `--maglev-truncation`, untagged-Phi variants.
- Representation transitions: elements kinds, maps, fields, typed arrays.
- Differential false-positive rate across GC/scheduling settings.
- Fault-injection canary detection rate and time-to-detection.

### Cross-cutting
- Corpus: cold start vs 1-hour vs multi-day corpus.
- Revision bisection for every candidate.
- Known-fixed bug regression suite to calibrate the harness.
- Flag matrix: `--future`, `--js-staging`, `--jit-fuzzing`,
  `--gc-interval`, `--single-threaded`.

## Caveats

- The matrix is a driver, not a guarantee of bug discovery.
- Trap mode needs `pku`/`ospke`; on CPUs without it use `v8Sandbox`.
- Result rows are independent campaigns; statistical noise is large. Run
  multiple seeds/repetitions before drawing conclusions.
- Keep storage paths separate per configuration and revision.
