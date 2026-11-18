#!/usr/bin/env python3

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Runs a matrix of V8 Fuzzilli campaigns and produces a results table.

The matrix is a TSV file with one experiment per row:
  id  profile  d8  asan_d8  jobs  duration  notes

`asan_d8` may be "-" to disable ASan. Each row is executed through
Tools/v8-vrp-campaign.sh and gets its own storage/logs directory.
Results are written as RESULTS.md, RESULTS.tsv, and RESULTS.json.
"""

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

FIELDS = ["id", "profile", "d8", "asan_d8", "jobs", "duration", "notes"]


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True, help="TSV matrix file.")
    parser.add_argument(
        "--out",
        type=Path,
        help="Output directory (default: /tmp/v8-fuzzing-matrix-<timestamp>).",
    )
    parser.add_argument(
        "--campaign",
        type=Path,
        help="Campaign driver (default: Tools/v8-vrp-campaign.sh next to this script).",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Pass --resume to each campaign."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without running them."
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep running remaining rows after a failed campaign.",
    )
    return parser.parse_args()


def parse_matrix(path):
    if not path.is_file():
        die(f"matrix file not found: {path}")
    rows = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if parts[0].strip().lower() == "id":
            continue
        if len(parts) < 6:
            die(f"{path}:{lineno}: expected at least 6 tab-separated fields")
        parts = [p.strip() for p in parts]
        row = dict(zip(FIELDS, parts))
        row["lineno"] = lineno
        rows.append(row)
    if not rows:
        die(f"matrix has no experiment rows: {path}")
    return rows


def duration_seconds(value):
    match = re.fullmatch(r"(\d+)([smh])", value)
    if not match:
        die(f"invalid duration (expected e.g. 30m): {value}")
    amount = int(match.group(1))
    return amount * {"s": 1, "m": 60, "h": 3600}[match.group(2)]


def parse_metadata(campaign_out):
    path = campaign_out / "metadata.txt"
    if not path.is_file():
        return ""
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("v8_revision="):
            return line.split("=", 1)[1].strip()
    return ""


def parse_summary(campaign_out):
    path = campaign_out / "SUMMARY.txt"
    if not path.is_file():
        return None
    text = path.read_text(errors="replace")
    crashes = None
    differentials = None
    for match in re.finditer(r"\] crashes=(\d+) differentials=(\d+)", text):
        crashes = int(match.group(1))
        differentials = int(match.group(2))
    return crashes, differentials


def parse_log_stats(campaign_out, profile):
    path = campaign_out / "logs" / f"{profile}.log"
    if not path.is_file():
        return {}
    text = path.read_text(errors="replace")
    stats = {}

    def last(pattern):
        matches = re.findall(pattern, text)
        return matches[-1] if matches else None

    execs = last(r"Total Execs:\s+(\d+)")
    rate = last(r"Execs / Second:\s+([0-9.]+)")
    correctness = last(r"Correctness Rate:\s+([0-9.]+)%")
    if execs is not None:
        stats["total_execs"] = int(execs)
    if rate is not None:
        stats["execs_per_second"] = float(rate)
    if correctness is not None:
        stats["correctness_rate"] = float(correctness)
    return stats


def main():
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    campaign = args.campaign or (root / "Tools" / "v8-vrp-campaign.sh")
    campaign = campaign.expanduser().resolve()
    if not campaign.is_file():
        die(f"campaign driver not found: {campaign}")

    matrix_path = args.matrix.expanduser().resolve()
    rows = parse_matrix(matrix_path)
    out = (
        args.out
        or Path("/tmp") / f"v8-fuzzing-matrix-{datetime.now():%Y%m%d-%H%M%S}"
    ).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "matrix.tsv").write_text(matrix_path.read_text())

    results = []
    for row in rows:
        row_out = out / row["id"]
        cmd = [
            str(campaign),
            "--d8",
            row["d8"],
            "--profiles",
            row["profile"],
            "--jobs",
            row["jobs"],
            "--duration",
            row["duration"],
            "--out",
            str(row_out),
        ]
        if row["asan_d8"] and row["asan_d8"] != "-":
            cmd += ["--asan-d8", row["asan_d8"]]
        if args.resume:
            cmd.append("--resume")

        print(f"[{row['id']}] {' '.join(shlex.quote(c) for c in cmd)}")
        if args.dry_run:
            results.append(
                {
                    **row,
                    "status": "dry-run",
                    "v8_revision": "",
                    "crashes": None,
                    "differentials": None,
                    "stats": {},
                    "output": str(row_out),
                }
            )
            continue

        timeout = duration_seconds(row["duration"]) + 900
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            rc = proc.returncode
            row_out.mkdir(parents=True, exist_ok=True)
            (row_out / "matrix-campaign-stdout.log").write_text(
                (proc.stdout or "") + (proc.stderr or "")
            )
        except subprocess.TimeoutExpired as e:
            rc = 124
            row_out.mkdir(parents=True, exist_ok=True)
            (row_out / "matrix-campaign-stdout.log").write_text(
                (e.stdout or "") + (e.stderr or "")
            )

        summary = parse_summary(row_out)
        crashes, differentials = summary if summary else (None, None)
        result = {
            **row,
            "status": "ok" if rc == 0 and summary is not None else f"exit={rc}",
            "v8_revision": parse_metadata(row_out),
            "crashes": crashes,
            "differentials": differentials,
            "stats": parse_log_stats(row_out, row["profile"]),
            "output": str(row_out),
        }
        results.append(result)

        if rc != 0 and not args.continue_on_error:
            print(f"[{row['id']}] campaign failed with exit {rc}", file=sys.stderr)
            break

    (out / "RESULTS.json").write_text(json.dumps(results, indent=2) + "\n")

    tsv_lines = [
        "\t".join(
            [
                "id",
                "profile",
                "v8_revision",
                "d8",
                "asan_d8",
                "jobs",
                "duration",
                "status",
                "crashes",
                "differentials",
                "total_execs",
                "execs_per_second",
                "correctness_rate",
                "notes",
            ]
        )
    ]
    for result in results:
        stats = result.get("stats") or {}
        tsv_lines.append(
            "\t".join(
                str(x)
                for x in [
                    result["id"],
                    result["profile"],
                    result.get("v8_revision", ""),
                    result["d8"],
                    result.get("asan_d8", "-"),
                    result["jobs"],
                    result["duration"],
                    result["status"],
                    result.get("crashes", ""),
                    result.get("differentials", ""),
                    stats.get("total_execs", ""),
                    stats.get("execs_per_second", ""),
                    stats.get("correctness_rate", ""),
                    (result.get("notes") or "").replace("\t", " "),
                ]
            )
        )
    (out / "RESULTS.tsv").write_text("\n".join(tsv_lines) + "\n")

    write_markdown(out, matrix_path, results)
    print(f"Results: {out / 'RESULTS.md'}")
    print(f"TSV:     {out / 'RESULTS.tsv'}")
    print(f"JSON:    {out / 'RESULTS.json'}")


def write_markdown(out, matrix_path, results):
    lines = [
        "# V8 fuzzing experiment matrix results",
        "",
        f"- generated: {datetime.now().isoformat()}",
        f"- matrix: `{matrix_path}`",
        f"- output: `{out}`",
        "",
        "| ID | Profile | Revision | Jobs | Duration | Status | Crashes | Differentials | Execs | Exec/s | Correctness | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        stats = result.get("stats") or {}
        lines.append(
            "| {id} | {profile} | {rev} | {jobs} | {duration} | {status} | "
            "{crashes} | {diffs} | {execs} | {rate} | {corr} | {notes} |".format(
                id=result["id"],
                profile=result["profile"],
                rev=(result.get("v8_revision") or "")[:12],
                jobs=result["jobs"],
                duration=result["duration"],
                status=result["status"],
                crashes=result.get("crashes", ""),
                diffs=result.get("differentials", ""),
                execs=stats.get("total_execs", ""),
                rate=stats.get("execs_per_second", ""),
                corr=stats.get("correctness_rate", ""),
                notes=(result.get("notes") or "").replace("|", "\\|"),
            )
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- Compare only rows with the same V8 revision and build configuration.",
        "- Trap (`v8SandboxTrap`) crashes are timing-dependent; treat logs as primary artifacts.",
        "- Fault-injection canaries are not VRP findings.",
        "- Recheck candidates against the latest V8 main before reporting.",
        "",
    ]
    (out / "RESULTS.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()


