# Postmortem — DR Drill Lab 23

Theo đúng template §4 "Sau Failover: Blameless Postmortem". Blameless: câu hỏi là
"hệ thống/process nào cho phép chuyện này", không phải "ai làm sai".

## 1. Timeline (mọi dòng phải có evidence path:line)

| ISO time | Sự kiện | Evidence |
|---|---|---|
| 2026-08-25T05:27:24 | Outage bắt đầu (Chaos ngắt kết nối mạng Region A) | `chaos/chaos-events.jsonl:4` |
| 2026-08-25T05:27:26 | User đầu tiên bị ảnh hưởng (Request timeout 503) | `reports/drill-2-withdr.jsonl:21` |
| 2026-08-25T05:27:40 | Health check alert (Chuyển Region A sang UNHEALTHY sau 3 lần fail) | `reports/health-events.jsonl:2` |
| 2026-08-25T05:27:46 | Operator confirm cutover & mở incident | `reports/runbook-run.jsonl:2` |
| 2026-08-25T05:27:50 | Resolved (Request đầu tiên thành công từ Region B, RTO hoàn tất) | `reports/drill-2-withdr.jsonl:30` |

## 2. RTO/RPO đo được vs mục tiêu — gap ở bước nào?

- RTO mục tiêu: 300s · đo được: 26.0s · gap: 274.0s (đạt mục tiêu sớm hơn 274.0s)
- RPO mục tiêu: 300s · đo được: 10.01s (5 doc bị mất) · gap: 289.99s
- **Bước tốn nhiều giây nhất:** `Health-check detection floor` (15.3s, chiếm 58.8% tổng RTO) — do cơ chế chống flapping yêu cầu 3 chu kỳ probe thất bại liên tiếp ($3 \times 5\text{s} = 15\text{s}$) trước khi xác nhận chuyển trạng thái sang `UNHEALTHY`.

## 3. Root cause (5 whys)

1. *Tại sao người dùng nhận lỗi 503?* Vì Region A gặp sự cố rớt mạng đột ngột (netblock), các kết nối TCP bị treo tới timeout.
2. *Tại sao hệ thống không chuyển vùng ngay lập tức?* Vì Health Checker cần 15s để kiểm tra liên tiếp 3 lần nhằm loại trừ lỗi mạng tạm thời (anti-flapping).
3. *Tại sao Region B không thể lập tức phục vụ khi Region A down?* Vì Region B hoạt động theo mô hình Active-Passive/Warm-standby, chưa có snapshot mới nhất và model weights chưa được load vào GPU.
4. *Tại sao cần 5 bước failover theo thứ tự nghiêm ngặt?* Vì nếu cutover DNS trước khi Region B nạp dữ liệu và warm-up xong `/readyz`, người dùng sẽ nhận lỗi 503 từ cả 2 phía, làm tăng RTO.
5. *Process/hệ thống nào đã giúp phục hồi?* Quy trình Runbook tự động hóa đã thực hiện restore state từ snapshot gần nhất, scale GPU pool và cutover DNS trong vòng 7.2s sau khi phát hiện outage.

## 4. Action items (có owner + deadline)

| # | Action | Owner | Deadline | Giảm RTO/RPO bao nhiêu giây |
|---|---|---|---|---|
| 1 | Tối ưu chu kỳ health check xuống `interval=3s, threshold=3` | SRE Team | 2026-09-15 | Giảm RTO ~6.0s |
| 2 | Chuyển sang cơ chế WAL streaming continuous replication cho Vector DB | Data Platform | 2026-09-30 | Giảm RPO xuống < 1.0s (0-1 doc lost) |
| 3 | Duy trì pre-warmed standby GPU pool tại Region B | AI Infra | 2026-10-05 | Giảm RTO ~0.5s |

## 5. Ba câu hỏi bắt buộc trả lời

1. **`interval × threshold` của bạn là bao nhiêu giây? Nó chiếm bao nhiêu % RTO?**
   - `5.0s × 3 = 15.0s`. Chiếm **57.7%** tổng thời gian RTO (15.0s / 26.0s).

2. **Nếu hạ interval xuống 1s, RTO giảm mấy giây — và bạn trả giá gì (§4 flapping)?**
   - RTO sẽ giảm **12.0s** (detection floor giảm từ 15s xuống 3s).
   - **Cái giá phải trả:** Hệ thống cực kỳ nhạy cảm với hiện tượng giật mạng (network jitter) hoặc packet drop thoáng qua. Bất kỳ sự cố mạng kéo dài 3 giây nào cũng sẽ kích hoạt failover nhầm lẫn, dẫn đến hiện tượng "flapping" (chuyển vùng qua lại liên tục giữa 2 region), làm đứt gãy phiên làm việc của người dùng và gây nguy cơ phân mảnh dữ liệu (split-brain).

3. **Nếu outage kéo dài 6 giờ và region chính mất dữ liệu vĩnh viễn, `docs_lost` của bạn có nghĩa gì với khách hàng?**
   - 5 documents bị mất đại diện cho các bản ghi giao dịch / ticket của người dùng gửi vào trong khoảng 10.01 giây trước khi sự cố xảy ra nhưng chưa kịp đồng bộ sang Region B qua chu kỳ replication.
   - Đối với khách hàng, các giao dịch này bị mất hoàn toàn và cần phải nhập lại, hoặc đội ngũ vận hành phải đối soát transaction log / audit trail từ hệ thống thanh toán / message queue ngoài để phục hồi lại dữ liệu cho khách hàng.
