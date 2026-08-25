"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    """Ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rec = {
        "ts": now,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)),
        "step": n,
        "name": name,
        **kw,
    }
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"RUNBOOK [{n}_{name}]", json.dumps(rec))
    return rec


def confirm(auto: bool, msg: str) -> bool:
    """auto=True -> True; ngược lại hỏi y/N."""
    if auto:
        return True
    try:
        ans = input(f"{msg} [y/N]: ").strip().lower()
        return ans in ("y", "yes")
    except EOFError:
        return True


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """7 bước quy trình Runbook ứng cứu sự cố."""
    t_start = time.time()
    
    # Bước 1: Xác nhận outage
    # Probe primary và target
    p_alive = False
    for _ in range(3):
        try:
            with httpx.Client(timeout=1.0) as c:
                r = c.get(f"{URL[primary]}/healthz")
                if r.status_code == 200:
                    p_alive = True
                    break
        except Exception:
            pass
        time.sleep(0.1)
        
    step(1, "xac_nhan_outage", primary=primary, primary_alive=p_alive, target=target)
    
    if not confirm(auto, f"Xác nhận thực hiện failover từ region '{primary}' sang '{target}'?"):
        return {"ok": False, "reason": "aborted_by_operator"}
        
    # Bước 2: Thông báo incident
    t_outage = None
    chaos_log = pathlib.Path("chaos/chaos-events.jsonl")
    if chaos_log.exists():
        for line in chaos_log.read_text().splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    if data.get("action") == "kill":
                        t_outage = data.get("ts")
                except Exception:
                    pass
                    
    step(2, "thong_bao_incident", operator_alert_ts=time.time(), t_outage_ts=t_outage,
         note="incident opened, RTO clock ticking")
         
    # Bước 3: Scale GPU pool (thực hiện failover 5 bước)
    fo_res = fo.failover(target=target, backend=backend)
    step(3, "scale_gpu_pool", failover_result=fo_res)
    if not fo_res.get("ok"):
        return {"ok": False, "step": 3, "failover_result": fo_res}
        
    # Bước 4: Verify state replica
    st = fo.state_of(target)
    step(4, "verify_state_replica",
         target=target,
         vector_count=st.get("count"),
         weights=st.get("weights"),
         pool_state=st.get("pool_state"),
         rpo_seconds=fo_res.get("rpo_seconds"),
         docs_lost=fo_res.get("docs_lost"),
         embed_model_version=fo_res.get("embed_model_version"))
         
    # Bước 5: DNS cutover (xác nhận trạng thái edge)
    step(5, "dns_cutover", active_region=target, ok=fo_res.get("ok"))
    
    # Bước 6: Verify golden signals (10 request thật)
    latencies = []
    errors = 0
    with httpx.Client(timeout=3.0) as c:
        for _ in range(10):
            t0 = time.time()
            try:
                r = c.get("http://127.0.0.1:8080/v1/infer", params={"q": "ping test"})
                lat = (time.time() - t0) * 1000
                latencies.append(lat)
                if r.status_code != 200:
                    errors += 1
            except Exception:
                errors += 1
            time.sleep(0.05)
            
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else None
    step(6, "verify_golden_signals", total_requests=10, error_count=errors,
         p95_latency_ms=round(p95, 1) if p95 is not None else None)
         
    # Bước 7: Post incident
    elapsed = round(time.time() - t_start, 2)
    measure_cmd = "python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300"
    step(7, "post_incident", elapsed_s=elapsed, measure_cmd=measure_cmd)
    
    return {
        "ok": True,
        "elapsed_s": elapsed,
        "target": target,
        "rpo_seconds": fo_res.get("rpo_seconds"),
        "docs_lost": fo_res.get("docs_lost"),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
