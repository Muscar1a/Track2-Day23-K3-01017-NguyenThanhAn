# Runbook 1 trang — Quy trình Failover khi Region chính Down

Runbook chuẩn hóa để kỹ sư On-call có thể thực thi chính xác và an toàn vào lúc 3h sáng. Mọi bước đều có lệnh copy-paste được, tiêu chí hoàn thành rõ ràng và phân định trách nhiệm cụ thể.

## 1. Bảng quy trình 7 bước ứng cứu

| # | Bước | Lệnh thực thi | Biết là xong khi | Ai làm |
|---|---|---|---|---|
| 1 | Xác nhận outage | `python dr/health_checker.py --interval 5 --threshold 3 --duration 20` hoặc `curl -s http://127.0.0.1:8001/readyz` | Region A trả về `UNHEALTHY` (fail $\ge 3$ lần liên tiếp) hoặc HTTP status `503` / timeout | On-call SRE |
| 2 | Mở incident + bấm giờ RTO | `python dr/runbook.py --primary a --target b --backend fs` | Khởi tạo incident thành công, timestamp $t_0$ và alert được ghi nhận vào `reports/runbook-run.jsonl` | Incident Commander |
| 3 | Restore state ở region phụ | `python state/snapshot.py get --region b --backend fs` | Manifest được nạp, file `vectors.sqlite` và weights `model.bin` được sao chép vào `state/region-b/` | On-call SRE |
| 4 | Scale pool warm→full | `echo full > state/region-b/pool_state && curl -s http://127.0.0.1:8002/readyz` | Endpoint `/readyz` của Region B trả về HTTP 200 `{"ready": true, "pool_state": "full"}` (sau thời gian warm-up) | On-call SRE |
| 5 | DNS/LB cutover | `echo b > edge/active_region && curl -s http://127.0.0.1:8080/edge/state` | Endpoint `/edge/state` trả về `{"active_region": "b"}` và cache TTL bắt đầu chu kỳ nhận diện mới | On-call SRE |
| 6 | Verify golden signals | `python -c "import httpx, time; c=httpx.Client(timeout=3); rs=[c.get('http://127.0.0.1:8080/v1/infer').status_code for _ in range(10)]; print('200 OK rate:', rs.count(200)/10)"` | 100% request trả về HTTP 200, latency p95 < 500ms, error rate = 0% | On-call SRE |
| 7 | Đo RTO + Postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Kết quả đo lường trả về `"rto_verdict": "PASS"` (RTO $\le$ 300s), dữ liệu log được lưu vào `reports/` | Incident Commander & Tech Lead |

---

## 2. Chính sách Rollback (Failback về Region A)

### Điều kiện Rollback:
1. **Region A đã hoạt động ổn định liên tục tối thiểu 30 phút:**
   - Endpoint `http://127.0.0.1:8001/readyz` trả về `200 OK` liên tục không có lỗi.
   - Không còn hiện tượng network flap / dropped packets.
2. **Dữ liệu mới nhất đã được đồng bộ ngược (Reverse Replication):**
   - Đã thực hiện snapshot từ Region B sang storage và restore sang Region A (`python state/snapshot.py put --region b && python state/snapshot.py get --region a`).
   - Kiểm tra `rpo` giữa 2 region đạt 0 documents lost (`python state/snapshot.py lag`).
3. **Thực hiện chuyển đổi trong Maintenance Window hoặc lưu lượng thấp:**
   - Tránh chuyển đổi ngược tự động hoàn toàn (full-auto) để ngăn ngừa split-brain hoặc flapping giữa 2 vùng.

### Thẩm quyền quyết định (Authority):
- **Incident Commander (IC)** cùng với **Lead SRE / System Architect** là người duy nhất có thẩm quyền phê duyệt lệnh Rollback sau khi xác nhận đủ 3 điều kiện trên.
