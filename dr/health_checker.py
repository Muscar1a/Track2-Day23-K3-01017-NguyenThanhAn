"""
Chạy:  python dr/health_checker.py --interval 5 --threshold 3 --duration 300 \
              --out reports/health-events.jsonl

CÂU HỎI PHẢI TRẢ LỜI TRƯỚC KHI VIẾT (ghi câu trả lời vào reports/postmortem.md):
  interval=5s, threshold=3 -> sớm nhất bạn có thể phát hiện outage là bao nhiêu giây?
  Con số đó nằm TRONG RTO của bạn. Muốn RTO 5 phút thì được phép chọn interval bao nhiêu?
"""
import argparse
import json
import pathlib
import time

import httpx

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def probe(region: str, timeout: float) -> tuple[bool, str]:
    """Trả về (ready, reason). Timeout bắt buộc để tránh treo request."""
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(f"{URL[region]}/readyz")
            if r.status_code == 200:
                body = r.json()
                if body.get("ready", False):
                    return True, "ok"
                reasons = body.get("reasons", ["not_ready"])
                return False, ",".join(reasons) if isinstance(reasons, list) else str(reasons)
            else:
                try:
                    reasons = r.json().get("reasons", [f"status_{r.status_code}"])
                    return False, ",".join(reasons) if isinstance(reasons, list) else str(reasons)
                except Exception:
                    return False, f"status_{r.status_code}"
    except Exception as e:
        return False, type(e).__name__


def run(interval: float, timeout: float, threshold: int, duration: float, out: pathlib.Path):
    """Vòng lặp poll + phát hiện transition + ghi JSONL."""
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    
    states = {
        r: {
            "state": "HEALTHY",
            "consecutive_fails": 0,
            "consecutive_successes": 0,
        }
        for r in ["a", "b"]
    }
    
    end_time = time.time() + duration
    while time.time() < end_time:
        t_start = time.time()
        for r in ["a", "b"]:
            ready, reason = probe(r, timeout)
            st = states[r]
            if ready:
                st["consecutive_successes"] += 1
                st["consecutive_fails"] = 0
                if st["state"] == "UNHEALTHY" and st["consecutive_successes"] >= threshold:
                    st["state"] = "HEALTHY"
                    now = time.time()
                    rec = {
                        "ts": now,
                        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)),
                        "event": "state_change",
                        "region": r,
                        "from": "UNHEALTHY",
                        "to": "HEALTHY",
                        "reason": reason,
                        "interval_s": interval,
                        "threshold": threshold,
                        "consecutive_successes": st["consecutive_successes"],
                    }
                    with out.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec) + "\n")
                    print("HEALTH", json.dumps(rec))
            else:
                st["consecutive_fails"] += 1
                st["consecutive_successes"] = 0
                if st["state"] == "HEALTHY" and st["consecutive_fails"] >= threshold:
                    st["state"] = "UNHEALTHY"
                    now = time.time()
                    rec = {
                        "ts": now,
                        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)),
                        "event": "state_change",
                        "region": r,
                        "from": "HEALTHY",
                        "to": "UNHEALTHY",
                        "reason": reason,
                        "interval_s": interval,
                        "threshold": threshold,
                        "consecutive_fails": st["consecutive_fails"],
                    }
                    with out.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec) + "\n")
                    print("HEALTH", json.dumps(rec))
                    
        elapsed = time.time() - t_start
        sleep_dur = max(0.0, interval - elapsed)
        if sleep_dur > 0 and time.time() + sleep_dur <= end_time:
            time.sleep(sleep_dur)
        elif time.time() >= end_time:
            break


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--threshold", type=int, default=3)
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--out", default="reports/health-events.jsonl")
    a = p.parse_args()
    run(a.interval, a.timeout, a.threshold, a.duration, pathlib.Path(a.out))
