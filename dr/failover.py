"""
Chạy:  python dr/failover.py --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from state import snapshot  # noqa: E402

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}
LOG = pathlib.Path("reports/failover-events.jsonl")


def emit(**kw):
    """Append 1 dòng JSONL có ts + iso vào LOG, và print ra stdout."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), **kw}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print("FAILOVER", json.dumps(rec))
    return rec


def state_of(region: str) -> dict:
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{URL[region]}/v1/state")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {"region": region, "pool_state": "unknown"}


def failover(target: str, backend: str = "fs", wait: float = 60.0) -> dict:
    """5 bước failover đúng thứ tự:
    1_verify_target -> 2_restore_snapshot -> 3_scale_pool -> 4_wait_ready -> 5_dns_cutover
    """
    primary = "a" if target == "b" else "b"
    
    # Bước 1: verify target
    st = state_of(target)
    emit(step="1_verify_target", target=target, target_state=st)
    
    # Bước 2: restore snapshot
    snap_meta = snapshot.get(target, backend)
    prim_db = pathlib.Path(f"state/region-{primary}/vectors.sqlite")
    rest_db = pathlib.Path(f"state/region-{target}/vectors.sqlite")
    rpo_info = snapshot.rpo(prim_db, rest_db)
    
    rpo_seconds = rpo_info.get("rpo_seconds")
    docs_lost = rpo_info.get("docs_lost")
    embed_version = snap_meta.get("embed_model_version")
    
    emit(
        step="2_restore_snapshot",
        target=target,
        backend=backend,
        snapshot_at=snap_meta.get("snapshot_at"),
        embed_model_version=embed_version,
        rpo_seconds=rpo_seconds,
        docs_lost=docs_lost,
    )
    
    # Bước 3: scale pool (warm -> full)
    pool_file = pathlib.Path(f"state/region-{target}/pool_state")
    pool_file.parent.mkdir(parents=True, exist_ok=True)
    pool_file.write_text("full\n", encoding="utf-8")
    emit(step="3_scale_pool", target=target, pool_state="full")
    
    # Bước 4: wait ready (poll /readyz)
    t4_start = time.time()
    ready = False
    while time.time() - t4_start < wait:
        try:
            with httpx.Client(timeout=1.0) as c:
                r = c.get(f"{URL[target]}/readyz")
                if r.status_code == 200:
                    body = r.json()
                    if body.get("ready", False):
                        ready = True
                        break
        except Exception:
            pass
        time.sleep(0.2)
        
    waited_s = round(time.time() - t4_start, 2)
    if not ready:
        emit(step="4_wait_ready", target=target, ok=False, waited_s=waited_s, error="timeout")
        return {"ok": False, "step": "4_wait_ready", "error": "timeout", "waited_s": waited_s}
        
    emit(step="4_wait_ready", target=target, ok=True, waited_s=waited_s)
    
    # Bước 5: DNS / Edge cutover
    active_file = pathlib.Path("edge/active_region")
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(f"{target}\n", encoding="utf-8")
    emit(step="5_dns_cutover", active_region=target, target=target, ok=True)
    
    return {
        "ok": True,
        "target": target,
        "rpo_seconds": rpo_seconds,
        "docs_lost": docs_lost,
        "waited_s": waited_s,
        "embed_model_version": embed_version,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="b", choices=["a", "b"])
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--wait", type=float, default=60)
    a = p.parse_args()
    print(json.dumps(failover(a.target, a.backend, a.wait), indent=2))
