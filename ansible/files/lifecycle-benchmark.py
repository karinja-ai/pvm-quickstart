#!/usr/bin/env python3
"""Measure CubeSandbox lifecycle stages and clean up each test sandbox."""

import argparse
import json
import os
import subprocess
import time
import traceback

from cubesandbox import Config, Sandbox


def now_ms(start):
    return round((time.perf_counter() - start) * 1000, 3)


def run_guest(sb, code):
    result = sb.run_code(code, timeout=600)
    if result.error is not None:
        raise RuntimeError(f"guest execution error: {result.error}")
    return "\n".join(result.logs.stdout).strip()


def snapshot_info(snapshot_id):
    proc = subprocess.run(
        [
            "cubemastercli",
            "cubebox",
            "snapshot",
            "info",
            "--snapshot-id",
            snapshot_id,
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def wait_remote_ready(snapshot_id, timeout_s):
    started = time.perf_counter()
    last = {}
    while time.perf_counter() - started < timeout_s:
        last = snapshot_info(snapshot_id)
        detail = last.get("snapshot", last)
        state = str(detail.get("remote_status", detail.get("remoteStatus", ""))).lower()
        if state == "ready":
            return last, round((time.perf_counter() - started) * 1000, 3)
        if state == "failed":
            raise RuntimeError(
                f"snapshot remote export failed: {json.dumps(last, sort_keys=True)}"
            )
        time.sleep(1)
    raise TimeoutError(
        f"remote snapshot did not become ready: {json.dumps(last, sort_keys=True)}"
    )


def pause_remote_state(sandbox_id):
    proc = subprocess.run(
        ["cubemastercli", "cubebox", "list", "--all", "--wide"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if sandbox_id in line:
            fields = line.split()
            if len(fields) >= 4:
                return fields[2], fields[3], proc.stdout
    return "", "missing", proc.stdout


def wait_pause_remote_ready(sandbox_id, timeout_s):
    started = time.perf_counter()
    backend, state, raw = "", "", ""
    while time.perf_counter() - started < timeout_s:
        backend, state, raw = pause_remote_state(sandbox_id)
        if state == "ready":
            return backend, state, raw, round((time.perf_counter() - started) * 1000, 3)
        if state == "failed":
            raise RuntimeError(f"paused package export failed: {raw}")
        time.sleep(1)
    raise TimeoutError(
        f"pause package did not become ready; last state={state!r}: {raw}"
    )


def benchmark_one(args, config, index, warmup):
    row = {
        "backend": args.backend,
        "template_id": args.template,
        "working_set_mib": args.working_set_mib,
        "sample_index": index,
        "warmup": warmup,
        "ok": False,
    }
    sb = None
    restored = None
    snapshot_id = None
    try:
        t = time.perf_counter()
        sb = Sandbox.create(template=args.template, timeout=900, config=config)
        row["create_api_ms"] = now_ms(t)
        row["sandbox_id"] = sb.sandbox_id
        info = sb.get_info()
        row["initial_state"] = info.get("state")
        row["running_state_ms"] = (
            row["create_api_ms"]
            if str(info.get("state", "")).lower() == "running"
            else None
        )

        if args.working_set_mib:
            size = args.working_set_mib
            state_started = time.perf_counter()
            code = (
                "import os\n"
                f"_cube_bench_workset=bytearray({size}*1024*1024)\n"
                f"_cube_bench_pages={size}*256\n"
                "for _cube_page in range(_cube_bench_pages):\n"
                "    _cube_offset=_cube_page*4096\n"
                "    _cube_bench_workset[_cube_offset:_cube_offset+8]=_cube_page.to_bytes(8,'little')\n"
                f"p='/tmp/cubesandbox-automation-{size}m.bin'\n"
                "with open(p,'wb') as f:\n"
                "    for _cube_start in range(0,_cube_bench_pages,256):\n"
                "        _cube_chunk=b''.join((_cube_bench_pages+_cube_page).to_bytes(8,'little')+bytes(4088) "
                "for _cube_page in range(_cube_start,min(_cube_start+256,_cube_bench_pages)))\n"
                "        f.write(_cube_chunk)\n"
                "    f.flush(); os.fsync(f.fileno())\n"
                "print(len(_cube_bench_workset),os.path.getsize(p),_cube_bench_pages)"
            )
            state_output = run_guest(sb, code)
            row["touched_state_output"] = state_output
            row["state_prepare_ms"] = round(
                (time.perf_counter() - state_started) * 1000, 3
            )
        else:
            row["first_guest_output"] = run_guest(sb, "print('cube-first-command-ok')")
        row["first_guest_command_ms"] = now_ms(t)

        ts = time.perf_counter()
        snap = sb.create_snapshot()
        snapshot_id = snap.snapshot_id
        row["snapshot_id"] = snapshot_id
        row["snapshot_api_ms"] = round((time.perf_counter() - ts) * 1000, 3)
        row["snapshot_info"] = snapshot_info(snapshot_id)
        if args.backend == "s3":
            row["snapshot_remote_info"], row["snapshot_remote_wait_ms"] = (
                wait_remote_ready(snapshot_id, args.remote_timeout)
            )
        else:
            row["snapshot_remote_wait_ms"] = None

        tp = time.perf_counter()
        sb.pause(wait=True, timeout=180, interval=0.25)
        row["pause_wait_ms"] = round((time.perf_counter() - tp) * 1000, 3)
        row["state_after_pause"] = sb.get_info().get("state")
        if args.backend == "s3":
            # The pause package is separate from the explicit snapshot.
            (
                row["pause_package_backend"],
                row["pause_remote_status"],
                row["paused_sandbox_list"],
                row["pause_remote_wait_ms"],
            ) = wait_pause_remote_ready(sb.sandbox_id, args.remote_timeout)

        tr = time.perf_counter()
        sb.resume(timeout=900)
        row["resume_api_ms"] = round((time.perf_counter() - tr) * 1000, 3)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = sb.get_info().get("state")
            if str(state).lower() == "running":
                break
            time.sleep(0.1)
        else:
            raise TimeoutError(f"sandbox did not resume; last state={state!r}")
        row["resume_running_ms"] = round((time.perf_counter() - tr) * 1000, 3)
        if args.working_set_mib:
            size = args.working_set_mib
            check_code = (
                "import os\n"
                "_cube_bench_memory_expected=_cube_bench_pages*(_cube_bench_pages-1)//2\n"
                "_cube_bench_file_expected=_cube_bench_pages*(3*_cube_bench_pages-1)//2\n"
                "_cube_bench_memory_sum=sum(int.from_bytes(_cube_bench_workset[i:i+8],'little') "
                "for i in range(0,len(_cube_bench_workset),4096))\n"
                f"p='/tmp/cubesandbox-automation-{size}m.bin'\n"
                "_cube_bench_file_sum=0\n"
                "with open(p,'rb') as f:\n"
                "    while True:\n"
                "        _cube_chunk=f.read(1024*1024)\n"
                "        if not _cube_chunk: break\n"
                "        _cube_bench_file_sum+=sum(int.from_bytes(_cube_chunk[i:i+8],'little') "
                "for i in range(0,len(_cube_chunk),4096))\n"
                "if _cube_bench_memory_sum!=_cube_bench_memory_expected or _cube_bench_file_sum!=_cube_bench_file_expected:\n"
                "    raise RuntimeError('state checksum mismatch')\n"
                "print(len(_cube_bench_workset),os.path.getsize(p),_cube_bench_memory_sum,_cube_bench_file_sum)"
            )
            check_started = time.perf_counter()
            row["resume_state_check"] = run_guest(sb, check_code)
            row["resume_state_check_ms"] = now_ms(check_started)
        else:
            row["resume_guest_output"] = run_guest(
                sb, "print('cube-resume-command-ok')"
            )

        tc = time.perf_counter()
        restored = Sandbox.create(template=snapshot_id, timeout=900, config=config)
        row["create_from_snapshot_api_ms"] = round((time.perf_counter() - tc) * 1000, 3)
        row["restored_sandbox_id"] = restored.sandbox_id
        restored_info = restored.get_info()
        row["create_from_snapshot_state"] = restored_info.get("state")
        row["create_from_snapshot_running_ms"] = (
            row["create_from_snapshot_api_ms"]
            if str(restored_info.get("state", "")).lower() == "running"
            else None
        )
        if args.working_set_mib:
            size = args.working_set_mib
            verify_code = check_code
            check_started = time.perf_counter()
            row["snapshot_state_check"] = run_guest(restored, verify_code)
            row["snapshot_state_check_ms"] = now_ms(check_started)
        else:
            row["snapshot_first_command"] = run_guest(
                restored, "print('cube-snapshot-restore-ok')"
            )
        row["create_from_snapshot_first_command_ms"] = now_ms(tc)
        row["ok"] = True
    except Exception as exc:  # noqa: BLE001 - record any failed benchmark stage
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc(limit=6)
    finally:
        for instance in (restored, sb):
            if instance is not None:
                try:
                    instance.kill()
                except Exception as exc:  # noqa: BLE001 - continue cleanup after any SDK error
                    row.setdefault("cleanup_errors", []).append(
                        f"kill {instance.sandbox_id}: {exc}"
                    )
        if snapshot_id:
            if args.defer_snapshot_delete:
                row["snapshot_delete_deferred"] = True
            else:
                try:
                    Sandbox.delete_snapshot(snapshot_id, config=config)
                    row["snapshot_deleted"] = True
                except Exception as exc:  # noqa: BLE001 - report snapshot cleanup errors
                    row.setdefault("cleanup_errors", []).append(
                        f"delete snapshot {snapshot_id}: {exc}"
                    )
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("xfs", "s3"))
    parser.add_argument("template")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--working-set-mib", type=int, choices=(0, 128, 512), default=0)
    parser.add_argument("--remote-timeout", type=int, default=900)
    parser.add_argument(
        "--defer-snapshot-delete",
        action="store_true",
        help="keep snapshots until every restore has finished, then drain and delete them",
    )
    parser.add_argument("--final-drain-seconds", type=int, default=120)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    proxy_node_ip = os.environ.get("CUBE_PROXY_NODE_IP")
    if not proxy_node_ip:
        parser.error("set CUBE_PROXY_NODE_IP to the public IP of the CubeSandbox node")
    config = Config(
        api_url=os.environ.get("CUBE_API_URL", "http://127.0.0.1:3000"),
        api_key=os.environ.get("CUBE_API_KEY", "e2b_000000"),
        template_id=args.template,
        proxy_node_ip=proxy_node_ip,
        request_timeout=60,
    )
    rows = []
    for i in range(args.warmups + args.runs):
        row = benchmark_one(args, config, i + 1, i < args.warmups)
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    deleted_snapshots = []
    if args.defer_snapshot_delete:
        time.sleep(args.final_drain_seconds)
        for row in rows:
            snapshot_id = row.get("snapshot_id")
            if not snapshot_id:
                continue
            try:
                Sandbox.delete_snapshot(snapshot_id, config=config)
                row["snapshot_deleted"] = True
                deleted_snapshots.append({"snapshot_id": snapshot_id, "deleted": True})
            except Exception as exc:  # noqa: BLE001 - report snapshot cleanup errors
                row.setdefault("cleanup_errors", []).append(
                    f"delete snapshot {snapshot_id}: {exc}"
                )
                deleted_snapshots.append(
                    {"snapshot_id": snapshot_id, "deleted": False, "error": str(exc)}
                )
    if args.output != "-":
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "backend": args.backend,
                    "template_id": args.template,
                    "rows": rows,
                    "deferred_snapshot_cleanup": deleted_snapshots,
                },
                f,
                indent=2,
            )
            f.write("\n")


if __name__ == "__main__":
    main()
