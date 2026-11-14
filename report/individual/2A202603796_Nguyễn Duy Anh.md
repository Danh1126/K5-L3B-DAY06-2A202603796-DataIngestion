# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline
- Chủ đề, nguồn/quyền, số trang và quy tắc tính trang: Sách lịch sử giáo dục *History of Education* (tác giả Levi Seeley, Project Gutenberg EBook #27963, định dạng EPUB, thuộc phạm vi Public Domain). Trích xuất nội dung chính từ 2 phần `h-3.htm.xhtml` và `h-4.htm.xhtml` (13 chương từ `CHAPTER XXX` đến `CHAPTER XLII`), gom tuần tự theo ranh giới đoạn văn thành 101 đơn vị nội dung (`page` đánh số từ `1` đến `101`), mỗi đơn vị có độ dài tối thiểu 1.500 (tổng cộng 191.803 ký tự).
- Chuẩn hóa, lỗi và giới hạn: Chuẩn hóa ký tự Unicode theo chuẩn NFC, loại bỏ khoảng trắng thừa trong từng đoạn nhưng bảo toàn ngắt đoạn `\n\n` để phục vụ chiến lược chia theo đoạn văn; loại bỏ trang bìa, mục lục và điều khoản bản quyền Project Gutenberg. Giới hạn: 2 đơn vị chứa cụm chú thích cuối phần (`page 1` và `page 51`) không nằm trong thẻ tiêu đề chương trực tiếp nên mang nhãn `chapter = "UNKNOWN"`, và việc chia `page` theo ngưỡng 1.500$ ký tự đôi khi tách một sự kiện liên tục qua hai `page` liền kề (như trường hợp Francis Bacon ở `page 22–23`).
- Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:
  - **Embedding:** OpenAI `text-embedding-3-small` (`1536` chiều, gọi qua `openai` Python SDK).
  - **Vector store:** Qdrant Local Persistent (`qdrant-client`, lưu cục bộ tại `starter/qdrant_db/`), độ đo tương đồng **Cosine** (`Distance.COSINE`), mỗi cấu hình A/B/C lưu trên collection riêng biệt (`edu_history_A`, `edu_history_B`, `edu_history_C`) với UUID5 sinh xác định từ `chunk_id` để đảm bảo tính idempotency khi nạp lại.
  - **Lệnh chạy & chi phí:** Chạy trọn bộ pipeline bằng `python -m src.run` trong môi trường `.venv`; tổng chi phí 3 lần ingest là **$0.002809** (`$0.000983` cho A, `$0.000913` cho B và `$0.000913` cho C).
- Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:
  - **Metadata bắt buộc:** `document_id` (`"gutenberg-27963"`), `source` (`"History of Education - Levi Seeley (PG #27963)"`), `page` (`1..101`), `chunk_id` (`document_id::strategy::pXXX::cYYY`).
  - **Trường lọc bổ sung:** `chapter` (`"CHAPTER XXX"` .. `"CHAPTER XLII"`, trích xuất tự động từ thẻ tiêu đề chương `<h2>`/`<h3>` trong cấu trúc XHTML của EPUB) và `part` (`"part_3"` / `"part_4"`).
  - **Lý do chọn:** Trong sách lịch sử giáo dục trình bày theo từng nhân vật/giai đoạn ở từng chương riêng biệt, các từ khóa về phương pháp sư phạm thường lặp lại nhiều nơi; lọc theo `chapter` giúp khoanh vùng đúng ngữ cảnh lịch sử mà không cần nhồi tên chương vào vector.

## Cấu hình và benchmark
- A / B / C (tham số cụ thể, khác biệt duy nhất B–C):
  - **Cấu hình A:** `fixed_size`, `chunk_size = 500` ký tự, `overlap = 50` ký tự, `filter = None`.
  - **Cấu hình B:** `by_paragraph` (gom các đoạn `\n\n` nguyên vẹn), `max_size = 800` ký tự, `overlap = 0`, `filter = None`.
  - **Cấu hình C:** `by_paragraph` (gom các đoạn `\n\n` nguyên vẹn), `max_size = 800` ký tự, `overlap = 0`, `filter = {"chapter": ...}` (bật Qdrant `FieldCondition` khớp chính xác trường `chapter` với các câu có khai báo `filter`).
  - **Khác biệt duy nhất B–C:** B và C dùng chung hoàn toàn tập `365` chunks và vector embedding; khác biệt duy nhất là C áp dụng bộ lọc metadata `chapter` ở bước truy vấn Qdrant cho các câu hỏi có điều kiện lọc.
- ≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:
  - Tổng **20 câu hỏi** (`benchmark/benchmark.json`): **15 câu `dev`** (`q01`–`q15`) và **5 câu `test`** (`q16`–`q20`), gồm câu trực tiếp, diễn đạt lại và điều kiện/ngoại lệ.
  - Có **4 câu metadata filter** (`q08`, `q10`, `q13` trong tập `dev` và `q20` trong tập `test`) sử dụng `filter: {"chapter": ...}`, diễn đạt tự nhiên và không lộ tên chương hay đáp án.
  - **Cách kiểm chứng evidence:** Toàn bộ 20 câu được khóa trước khi chạy truy xuất; script kiểm tra tự động xác nhận chuỗi `evidence_quote` (đã chuẩn hóa khoảng trắng) khớp nguyên văn 100% trong văn bản của `gold_page`.
- Tiêu chí chọn chiến lược đã chốt trước khi xem test: Thứ tự ưu tiên chốt trước khi đọc tập `test`: 1. `Dev Evidence Hit@3` cao nhất (kèm tuân thủ `100%` filter với câu có điều kiện lọc) -> 2. Điểm thủ công `Chunk Coherence` và `Grounding quality` cao hơn -> 3. Tài nguyên gọn hơn (ít chunk, thời gian nạp nhanh và chi phí embedding thấp hơn).

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 9/15 (60.0%) | 10/15 (66.7%) | 468 | 14.097s | $0.000983 |
| A | test | 2/5 (40.0%) | 3/5 (60.0%) | 468 | 14.097s | $0.000983 |
| B | dev | 9/15 (60.0%) | 12/15 (80.0%) | 365 | 9.668s | $0.000913 |
| B | test | 3/5 (60.0%) | 5/5 (100.0%) | 365 | 9.668s | $0.000913 |
| C | dev | 9/15 (60.0%) | 12/15 (80.0%) | 365 | 9.559s | $0.000913 |
| C | test | 3/5 (60.0%) | 5/5 (100.0%) | 365 | 9.559s | $0.000913 |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1.00 / 2 (n=10) | 9/15 (60.0%) | N/A | 0: 2 câu, 1: 0 câu, 2: 3 câu — TB: **1.20 / 2** |
| B | 2.00 / 2 (n=10) | 12/15 (80.0%) | N/A | 0: 0 câu, 1: 0 câu, 2: 5 câu — TB: **2.00 / 2** |
| C | 2.00 / 2 (n=10) | 14/15 (93.3%) | 4/4 (100.0%) | 0: 0 câu, 1: 0 câu, 2: 5 câu — TB: **2.00 / 2** |

Đường dẫn trace, nhãn thủ công và cách chọn mẫu:
- **Trace tự động:** `starter/results/trace_strategy_A.json`, `starter/results/trace_strategy_B.json`, `starter/results/trace_strategy_C.json` và tổng hợp `starter/results/metrics_summary.json`.
- **Nhãn thủ công:** `starter/results/manual_audit_completed.md` (tạo từ mẫu `starter/results/manual_coherence_template.csv` và trace tập `test`).
- **Cách chọn mẫu:** (1) *Chunk Coherence* chấm cố định chunk đầu tiên của 10 trang đầu tiên (`page = 1..10`, `n = 10`) trên cả 3 chiến lược; (2) *Metadata đủ và đúng* kiểm tra toàn bộ 15 kết quả Top-3 của 5 câu `test` (`N = 15`); (3) *Grounding* chấm dựa trên ngữ cảnh Top-3 của 5 câu `test` (`q16`–`q20`).

## Phân tích và kết luận
- So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:
  - 1. Retrieval accuracy (Hit@1 & Evidence Hit@3):** Chuyển từ cắt cứng `500/50` (A) sang gom đoạn văn `max 800` (B) nâng `Dev Evidence Hit@3` từ `10/15 (66.7%)` lên `12/15 (80.0%)` và `Test Evidence Hit@3` từ `3/5 (60.0%)` lên `5/5 (100.0%)`; B và C đạt cùng điểm accuracy tự động vì bộ lọc `chapter` trên `q08, q10, q13, q20` giữ vững các kết quả đúng vốn đã nằm trong Top-3 của B. Theo đúng định nghĩa một chunk đơn lẻ phải chứa đủ `evidence_quote`, các trường hợp bằng chứng bị tách qua 2 chunk liên tiếp ở Chiến lược A đều bị tính là lỗi (`Hit@3 = 0/1`) chứ không hợp đa chunk.
  - 2. Chunk coherence:** Trên cố định 10 vị trí đầu tiên (`page = 1..10`, chọn trước khi xem điểm), Chiến lược A đạt **1.00 / 2** (`10/20` điểm, tất cả đều bị cắt ngang giữa câu hoặc giữa cụm chú thích tại mốc 500 ký tự), trong khi B và C đạt **2.00 / 2** (`20/20` điểm, giữ trọn vẹn ranh giới đoạn văn `\n\n` và mạch lập luận).
  - 3. Metadata usefulness & Filter compliance:**
    - Ích lợi và hạn chế của trường metadata: Trường `chapter` giúp khoanh vùng đúng bối cảnh nhân vật/thời kỳ lịch sử (loại bỏ nhiễu chéo chương ở `q13` và `q20`), còn cặp `(source, page)` giúp truy vết ngược chính xác về đơn vị văn bản gốc để đối chiếu `evidence_quote`. Tuy nhiên, hạn chế của metadata hiện tại là nhãn `chapter` trích xuất tự động từ thẻ tiêu đề `<h2>/<h3>` khiến 2 trang chú thích cuối phần (`page 1`, `page 51`) bị gán `UNKNOWN`, và granularity ở cấp `page` ($\ge 1.500$ ký tự) chưa phân tách được các tiểu mục nhỏ trong cùng một trang.
    - *Chi tiết lỗi trên 15 bản ghi Top-3 tập `test` (`q16`–`q20`):* Chiến lược A đạt 9/15 (lỗi 6 bản ghi do kéo nhầm chương khác ở `q16` rank 3 [`p.52, CHAPTER XXXVI`], `q17` rank 2–3 [`p.69, p.74, CHAPTER XXXVIII`], `q18` rank 3 [`p.19, CHAPTER XXXII`] và `q20` rank 2–3 [`p.99, p.97`]); Chiến lược B đạt 12/15 (lỗi 3 bản ghi ở `q17` rank 2–3 [`p.69, p.74`] và `q18` rank 3 [`p.19`]); Chiến lược C đạt 14/15 (chỉ còn 1 bản ghi lệch chương ở `q18` rank 3 [`p.19, CHAPTER XXXII`] do `q18` là câu không bật filter) và đạt tuân thủ filter 4/4 (100.0%) (`3/3` trên `dev`, `1/1` trên `test`).
  - 4. Grounding quality (đánh giá thủ công mức độ đầy đủ bằng chứng truy xuất trên 5 câu `test`, không phải điểm sinh câu trả lời LLM):** Chiến lược A đạt trung bình 1.20 / 2 (`3` câu mức `2`: `q16, q17, q19` đủ bằng chứng; `0` câu mức `1`; `2` câu mức `0`: `q18` và `q20` do bằng chứng bị cắt đôi làm mất mốc năm `1860` và hình phạt đối với phụ huynh). Chiến lược B và C đều đạt trung bình 2.00 / 2 (`5` câu mức `2`: toàn bộ `q16`–`q20` đều chứa trọn vẹn cả điều kiện lẫn hệ quả trong Top-3 để trả lời và truy nguồn đầy đủ).
  - 5. Data strategy impact & 2 ví dụ sai cụ thể:**
    - *So sánh A–B và B–C:* B vượt trội A trên cả độ chính xác (`Test Hit@3` tăng `+40%`), coherence (`+1.00/2`), grounding (`+0.80/2`) lẫn tài nguyên (giảm `22%` số chunk từ `468 → 365`, giảm `31.4%` thời gian ingest `14.097s → 9.668s` và giảm `7.1%` chi phí embedding). C giữ toàn bộ ưu thế của B đồng thời nâng độ sạch metadata tập `test` từ `12/15` lên `14/15` nhờ bộ lọc `chapter`.
    - *Ví dụ sai 1 (`q18` và `q20` — Chiến lược A, nguồn `gutenberg-27963`, `page 84` & `page 98`):* Cả hai câu đều kéo đúng trang lên Top-1 (`gutenberg-27963::A::p084::c002` và `p098::c001`) nhưng trượt `Hit@3 = 0/1` do cửa sổ cứng 500 ký tự cắt đôi `evidence_quote` qua hai chunk liên tiếp; B và C giữ nguyên đoạn văn nên đạt `Hit@3 = 1/1`.
    - *Ví dụ sai 2 (`q11` — Chiến lược B/C, nguồn `gutenberg-27963`, `page 59`, `CHAPTER XXXVI`):* Hỏi về cuốn sách duy nhất được phép cho Émile đọc (*Robinson Crusoe*, `gold_page = 59`). A đạt `Hit@3 = 1/1` (`gutenberg-27963::A::p059::c002`), nhưng B và C trượt `Hit@3 = 0/1` (đẩy đoạn tổng quan tuổi 12–15 ở `p.58` lên Top-1) vì khi gom các đoạn dài tới 800 ký tự, chi tiết ngắn nằm cuối đoạn về *Robinson Crusoe* bị pha loãng mật độ ngữ nghĩa.
- Chiến lược chọn, đánh đổi, điều kiện áp dụng:
  - **Chiến lược chọn:** **Chiến lược C (`by_paragraph`, `max_size = 800` + `chapter` metadata filter)** theo đúng tiêu chí đã chốt trước test.
  - **Đánh đổi & điều kiện áp dụng:** Trong phạm vi corpus sách lịch sử giáo dục phân chương rõ ràng (*History of Education*, PG #27963) — không suy rộng cho mọi loại tài liệu phi cấu trúc — C tối ưu đồng thời độ chính xác, grounding và chi phí. Đánh đổi của C là phụ thuộc vào bước trích xuất cấu trúc chương chính xác lúc ingest và yêu cầu truy vấn đầu vào phải xác định đúng tên chương (nếu lọc sai `chapter` sẽ trả về rỗng; với truy vấn mở không rõ chương cần fallback về B).
- Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:
  - Tập `test` chỉ gồm `5` câu nên mỗi câu tương ứng biên độ sai số `20%`; 2 trang chú thích cuối phần bị gán `chapter = "UNKNOWN"`; việc chia `page` theo ngưỡng cứng >= 1.500$ ký tự đôi khi cắt đôi một sự kiện liên tục qua 2 trang (`page 22–23` ở `q08`); ngoài ra thời gian ingest chịu ảnh hưởng nhẹ bởi độ trễ mạng khi gọi OpenAI API.
- Nếu làm lại hoặc mở rộng, cải tiến gì?
  1. Bổ sung gối đầu 1 câu giữa các chunk đoạn văn (sentence-level overlap) và chia ranh giới `page` mềm theo cụm chủ đề để tránh tách đôi sự kiện liên tục (`q08`).
  2. Kết hợp Hybrid Search (Dense Vector + Sparse BM25) nhằm bắt chính xác các thực thể/tên riêng ngắn (như *Robinson Crusoe* ở `q11`) trong các đoạn văn dài.
  3. Mở rộng tập benchmark lên `50–100` câu có thêm truy vấn đa chương (multi-hop) và câu hỏi không có đáp án trong corpus (unanswerable).