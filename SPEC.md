§G
Dashboard quota luôn hiển thị đủ profile Codex từ WSL và Windows mà không mất snapshot khi một nguồn quét lỗi.

§C
- Python Windows phải đọc output WSL UTF-8.
- Không log token/auth secret.
- Dashboard tiếp tục bind 127.0.0.1:8787.

§I
- I1: `lib.paths.wsl_run(args, timeout)` chạy lệnh trong WSL và trả `CompletedProcess` text.
- I2: `bin/buzz_quota.py` quét quota và ghi `codex_account_limits`.
- I3: `bin/buzz_collector.py` trên Windows = `run_via_wsl(args)`: chụp `usage.db` ra bản sao tạm, collector WSL ghi bản sao, Windows `merge_scratch` (cột tường minh, một transaction) thay toàn bộ `requests`/`usage_events`/`usage_aggregates`, upsert `agents`/`principals`, xóa agent `claude-cli`/`agy` + snapshot hạn mức của chúng và principal là pubkey agent. Gộp trước, in log sau (UTF-8).
- I4: `bin/dashboard.py` phục vụ bằng `DashboardServer` (bind độc quyền 8787).

§V
- V1: Output UTF-8 từ WSL phải decode thành công trên Windows dù code page hệ thống không phải UTF-8.
- V2: WSL scan lỗi, output rỗng, hoặc JSON hỏng phải hủy refresh; không thay `codex_account_limits` bằng snapshot chỉ có Windows.
- V3: Refresh thành công phải ghi đủ account thu được từ các nguồn đã cấu hình.
- V4: ∀ ghi `usage.db` ! từ tiến trình Windows; WSL chỉ ghi bản sao tạm journal DELETE; bản sao lỗi/hỏng ⇒ giữ nguyên `usage.db`; `buzz_collector` / `buzz_quota` (trừ `--dump-json`) / `buzz_rebuild` chạy trong WSL gặp DB `/mnt/...` (realpath) không phải bản sao ⇒ từ chối (rc 2). Log/stdout không mã hóa được ⇒ không được làm hỏng lần gộp; timeout collector (480 s) + 2×60 s chờ khóa < timeout dashboard (780 s).
- V5: Tại một thời điểm chỉ một dashboard giữ 8787; bản thứ hai bind lỗi và thoát trước khi khởi tạo DB hay chạy poller.

§T
id|status|task|cites
T1|x|Fix UTF-8 decode và fail-closed WSL scan|V1,V2,I1,I2
T2|x|Thêm test hồi quy|V1,V2
T3|x|Refresh DB và xác nhận 4 profile|V3,I2
T4|x|Collector ghi qua bản sao tạm + dashboard bind độc quyền; test `tests/test_collector_single_writer.py`|V4,V5,I3,I4
T5|x|Dựng lại usage.db hỏng, chạy collector thật 2 vòng + làm mới trực tiếp, integrity ok|V4
T6|x|Sau code review: UTF-8 + gộp trước khi in, ngân sách timeout, chặn quota/rebuild ghi từ WSL, cột tường minh; 16 test; dashboard chạy không PYTHONIOENCODING vẫn gộp được|V4

§B
id|date|cause|fix
B1|2026-09-14|`subprocess.run(text=True)` dùng cp1252 làm mất stdout UTF-8; writer vẫn thay toàn bộ bảng bằng scan Windows|V1,V2
B3|2026-09-15|`run_via_wsl` in stdout WSL (tên tiếng Việt) TRƯỚC khi gộp; dashboard do watchdog bật không có PYTHONIOENCODING ⇒ stdout pipe cp1252 strict ⇒ UnicodeEncodeError ⇒ rc 1 ⇒ không gộp, dashboard lặng lẽ ngừng cập nhật|V4
B2|2026-09-14|collect_poller mỗi 10 phút cho collector WSL ghi thẳng `usage.db` qua /mnt/d khi dashboard Windows đang mở WAL → khóa không đồng bộ → "database disk image is malformed", trang chủ 500 (`'int' object has no attribute 'strip'`); `ThreadingHTTPServer` bật SO_REUSEADDR nên watchdog đẻ 2 dashboard cùng ghi|V4,V5
