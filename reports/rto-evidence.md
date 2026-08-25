# RTO/RPO Evidence — Lab 23

Báo cáo bằng chứng đo lường thực tế từ quá trình chạy Drill 1 (Baseline không có DR) và Drill 2 (Có cơ chế DR tự động). Mọi con số đều được kiểm chứng và đối chiếu từ các dòng log thực tế.

## 1. Drill 1 — không có DR (baseline)

| Chỉ số | Giá trị | Cách đo | Evidence |
|---|---|---|---|
| t_outage | `2026-08-25T05:20:43` | chaos kill | `chaos/chaos-events.jsonl:2` |
| Request fail đầu tiên | `+2.7s` | dòng `ok:false` đầu tiên sau t_outage | `reports/drill-1-nodr.jsonl:11` |
| Request thành công sau đó | không có | không có dòng `ok:true` nào sau t_outage | `reports/measure-drill-1.json` |
| RTO | `NO_RECOVERY` | `tools/measure_rto.py` | `reports/measure-drill-1.json` |

## 2. Drill 2 — có DR

| Mốc | +giây từ t_outage | Cách đo | Evidence |
|---|---|---|---|
| t_outage (mốc 0) | 0s | `action:kill` | `chaos/chaos-events.jsonl:4` |
| User thấy lỗi đầu tiên | 2.1s | dòng `ok:false` đầu | `reports/drill-2-withdr.jsonl:21` |
| Health check phát hiện | 15.3s | `to:UNHEALTHY, region:a` | `reports/health-events.jsonl:2` |
| Snapshot restore xong | 22.0s | `step:2_restore_snapshot` | `reports/failover-events.jsonl:6` |
| Region phụ ready | 22.5s | `step:4_wait_ready` | `reports/failover-events.jsonl:8` |
| DNS cutover | 22.5s | `step:5_dns_cutover` | `reports/failover-events.jsonl:9` |
| **RTO đo được** | 26.0s | dòng `ok:true` đầu sau lỗi | `reports/drill-2-withdr.jsonl:30` |

| Chỉ số | Đo được | Mục tiêu (slide §1) | Verdict |
|---|---|---|---|
| RTO — Inference API | 26.0s | 300s (5 phút) | PASS |
| RPO — Vector DB | 10.01s / 5 doc | 300s (5 phút) | PASS |

## 3. RTO của tôi gồm những gì (bắt buộc — đây là phần chấm điểm hiểu bài)

| Thành phần | Giây | Nó đến từ đâu | Giảm được bằng cách nào |
|---|---|---|---|
| Health-check detect floor | 15.0s | `interval_s × threshold` trong `reports/health-events.jsonl:2` | Giảm interval từ 5s xuống 2-3s (chấp nhận đánh đổi nguy cơ flapping khi mạng chập chờn) |
| Snapshot restore | 0.1s | 2_restore → 3_scale trong `reports/failover-events.jsonl:6` | Dùng lưu trữ NVMe SSD tốc độ cao, đồng bộ liên tục (continuous streaming / delta sync) |
| GPU pool warm-up | 0.5s | `waited_s` ở `4_wait_ready` trong `reports/failover-events.jsonl:8` | Duy trì GPU pool ở mức warm (pre-warmed pool) thay vì cold |
| DNS/LB TTL cache | 3.5s | t_recovered − t_cutover (`reports/drill-2-withdr.jsonl:30` vs `reports/failover-events.jsonl:9`) | Hạ TTL của DNS record xuống 1-2s hoặc sử dụng Anycast / dynamic routing ở tầng Global Load Balancer |
