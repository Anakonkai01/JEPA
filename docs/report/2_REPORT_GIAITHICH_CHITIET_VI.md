# Giải thích chi tiết (tiếng Việt) — bám dàn ý REPORT FULL

> Tài liệu này **đi theo đúng bố cục §1–§19 của `2_REPORT_FULL.md`**. Mỗi mục: tóm lại ý của report
> rồi **đào sâu thêm** (trực giác, ví dụ, cơ chế, code). Hai chỗ được mở rộng nhiều nhất:
> - **§9** — kiến trúc AC Predictor + **position embedding** (kèm code thật).
> - **§13** — các **biến thể descriptor định vị** đã thử thay cho cosine gốc (cosine thuần, centered
>   cosine, centered-spatial, bỏ-top-PC, whiten-shrink, SeqSLAM): làm gì, đo thế nào, cài ở đâu.
>   *(Lưu ý: report gốc §13.3 mới liệt kê chỉnh-ngưỡng / cùng-phiên / GPS-gate / quét-CEM — CHƯA mô tả
>   các biến thể descriptor này; đây là phần bổ sung, nên cân nhắc đưa vào report.)*

---

## §1. Tóm tắt & Đóng góp

**Report nói gì.** Đóng băng V-JEPA 2.1 (ViT-L 384) làm "mắt"; huấn luyện một AC Predictor ~39,2M tham
số học "hành động → đổi latent"; dùng CEM lập kế hoạch tới một ảnh mục tiêu. Đánh giá 3 tầng: Tier 1
(offline) đạt, Tier 2 (open-loop) đạt, Tier 3 (closed-loop ngoài trời) chưa tự lái — và khoảng cách
nằm ở **khâu định vị**, không phải mô hình thế giới.

**Đào sâu — vì sao chia 3 tầng?** Đây là một thiết kế *để quy trách nhiệm khi hỏng*. Nếu chỉ chạy thử
ngoài trời rồi báo "không chạy được", ta không biết lỗi ở đâu: ở predictor? ở planner? ở định vị? ở
cảm biến? Ba tầng tách bài toán theo độ khó tăng dần, mỗi tầng loại trừ một nghi phạm:
- Tier 1 chứng minh **predictor học đúng** (loại nghi phạm "mô hình thế giới kém").
- Tier 2 chứng minh **planner chọn đúng như người** (loại nghi phạm "CEM ngớ ngẩn").
- Tier 3 cho thấy vẫn lệch → vì đã loại 2 nghi phạm trên, lỗi **buộc phải** nằm ở phần còn lại = **định
  vị** (chọn ảnh mục tiêu kế) + ràng buộc cảm biến/độ trễ.

Đây chính là giá trị khoa học của báo cáo: không phải "đã làm xe tự lái" mà là **"chỉ ra chính xác nút
thắt"** bằng đo đạc, thay vì đoán mò.

**3 đóng góp, diễn giải lại:**
1. Mang dòng V-JEPA 2 từ **cánh tay robot** (cảnh bàn cố định) sang **robot di động ngoài trời** — chế
   độ khó hơn nhiều về độ bền (ánh sáng/hướng/lệch ngang).
2. Một nghiên cứu **open-loop** tách "năng lực lập kế hoạch" khỏi "độ bền closed-loop".
3. Một **phân tích hỏng có cơ chế, định lượng** — định vị nút thắt vào descriptor định vị, không gán
   nhãn mơ hồ.

---

## §2. Giới thiệu & Động lực

**Report nói gì.** World model học tự giám sát (họ JEPA của LeCun) cho phép "hiểu vật lý cảnh" không
nhãn. Meta đã chạy thật trên cánh tay Franka với V-JEPA 2-AC. Câu hỏi: cùng biểu diễn đó có hợp với một
xe di động ngoài trời không? Vì ViT-L cần GPU (không chạy trên điện thoại) nên suy luận qua PC; sau vài
ngày tinh chỉnh thực địa, chẩn đoán lỗi ở khâu định vị → dừng thực địa, củng cố offline + open-loop.

**Đào sâu — "động lực" thật sự là gì.** Điểm hấp dẫn của hướng này: thay vì gán nhãn hàng vạn ảnh
(tốn kém, không mở rộng được), ta tận dụng một **encoder nền tảng đã học sẵn từ >1 triệu giờ video**.
Phần "thông minh thị giác" đã có sẵn và miễn phí; ta chỉ cần dạy một phần nhỏ ("hành động làm cảnh đổi
ra sao"). Đó là lý do AC Predictor chỉ ~39,2M tham số mà vẫn hoạt động — nó *đứng trên vai* encoder.

**Vì sao dừng thực địa là một quyết định đúng (không phải bỏ cuộc).** Khi đo thấy lỗi nằm ở định vị
chứ không ở tham số mô hình, việc tiếp tục tinh chỉnh CEM/huấn luyện thêm sẽ **không** giải quyết được
gốc. Hợp lý hơn là chốt lại các kết quả đã vững (Tier 1, 2) và trình bày Tier 3 như một phân tích cơ
chế — đúng tinh thần nghiên cứu trung thực.

---

## §3. Phát biểu bài toán & Phạm vi

**Report nói gì.** Bài toán = **điều hướng thị giác theo mục tiêu**: cho (chuỗi) ảnh mục tiêu, mỗi bước
CEM chọn `[steer, throttle]` đưa cảnh hiện tại tiến về cảnh mục tiêu; mục tiêu khuất → xâu chuỗi các
subgoal nhìn-thấy-được. KHÔNG né vật cản, KHÔNG SLAM. Hai tầng tách bạch: **định vị** (thị giác + GPS)
và **điều khiển** (AC predictor + CEM).

**Đào sâu — "không phải bắt chước" nghĩa là gì.** Điểm dễ nhầm: thu thập ảnh subgoal nghe giống "ghi
lại đường đi để phát lại" (imitation). Khác biệt mấu chốt: ta **không ghi lại hành động** để tua lại.
Ta chỉ ghi lại **ảnh mục tiêu**. Hành động được **sinh mới** mỗi lần chạy bởi CEM, từ so sánh cảnh hiện
tại với ảnh mục tiêu. Hệ quả: nếu xe bị đẩy lệch, CEM vẫn tính hành động mới để quay về mục tiêu (miễn
là còn "thấy" mục tiêu) — khác hẳn phát-lại-băng vốn sẽ lặp lại y hệt chuỗi cũ bất kể xe đang ở đâu.

**Vì sao tách 2 tầng lại quan trọng.** Chính sự tách bạch này cho phép kết luận cuối: đo riêng được
rằng **tầng điều khiển bền** (patch-L1 đổi <5% khi nắng→mây) trong khi **tầng định vị sụp** (cosine
pooled). Nếu trộn chung, ta không thể nói lỗi ở đâu.

---

## §4. Khái niệm & Thước đo

**Report nói gì.** Định nghĩa: latent/patch token (576×1024), horizon H, rollout@k, baseline identity
("cảnh đứng yên"), năng lượng `E = ‖ẑ − z_goal‖₁`, argmin-E, contrast (độ sâu thung lũng), sign-turn,
open-loop vs closed-loop.

**Đào sâu — 3 khái niệm dễ hiểu sai:**

- **`rollout@k / identity < 1` KHÔNG có nghĩa "lái tốt".** Nó chỉ nghĩa "dự đoán tốt hơn giả định cảnh
  đứng yên" — một mốc **tối thiểu**. Vì sao cần mốc này? Xem "collapse" ở §11.

- **Contrast quan trọng hơn vị trí đáy thung lũng.** Hãy hình dung mặt năng lượng `E` theo trục lái.
  CEM cần một **thung lũng sâu, rõ** để biết bẻ lái về đâu. Nếu mặt phẳng (contrast ≈ 0), mọi góc lái
  "tốt như nhau" → CEM chọn bừa. Rất nhiều lỗi ở §13 **không phải** "đáy sai chỗ" mà là "**thung lũng
  biến mất**". Nhớ kỹ điều này.

- **Open-loop ≠ closed-loop.** Open-loop: video phát lại lượt người lái, mô hình **chỉ đề xuất** (khung
  kế đã cố định) → đo "nếu được chọn, mô hình có chọn giống người không". Closed-loop: mô hình **thực
  sự lái**, hành động của nó quyết định khung kế → có vòng phản hồi → mọi sai số tích luỹ. Một planner
  hoàn hảo open-loop vẫn có thể hỏng closed-loop nếu định vị/độ-trễ/cảm-biến kém — đó đúng là chuyện
  xảy ra.

---

## §5. Bối cảnh & Công trình liên quan

**Report nói gì.** World model = mô phỏng thế giới trong đầu agent để "tưởng tượng hậu quả hành động"
rồi lập kế hoạch. JEPA = dự đoán trong không gian biểu diễn (không dự đoán pixel). V-JEPA (video) →
V-JEPA 2 (>1 triệu giờ, mạnh) → V-JEPA 2.1 (ViT-L chưng cất, 384px, Dense Predictive Loss → patch
feature dày). V-JEPA 2-AC = biến thể có-điều-kiện-hành-động trên encoder đông cứng (kiến trúc tham
chiếu chính). ViNG = ý tưởng "đi tới ảnh mục tiêu".

**Đào sâu — vì sao "dự đoán pixel" là sai lầm.** Nếu bắt mô hình vẽ lại từng pixel khung kế: (1) nó
tốn dung lượng vẽ lá rung, bóng nắng nhấp nháy, nhiễu cảm biến — thứ vô nghĩa cho lái; (2) tương lai
bất định (lá có thể bay nhiều hướng) → ép "vẽ đúng" là ép làm điều bất khả thi. JEPA né cả hai bằng
cách dự đoán **đặc trưng trừu tượng** ("có lối rẽ trái, cây bên phải") thay vì RGB từng điểm — dễ hơn
và đúng trọng tâm điều khiển.

**Vì sao "Dense Predictive Loss" của 2.1 lại quan trọng cho dự án này.** Nó làm **mỗi patch** có một
descriptor tốt (đặc trưng *dày*, không chỉ một vector tổng thể). Ta giữ cả 576 patch để có **thông tin
không gian** — biết "lối đi đang ở bên trái khung hình" → biết bẻ lái hướng nào. Nếu encoder chỉ cho
một vector tổng thể tốt mà patch kém, ý tưởng này sụp.

---

## §6. Phần cứng & Thu thập dữ liệu

**Report nói gì.** Xe RC địa hình + ESP32-S3 điều khiển servo lái (MG946R, 1000–2000µs, tâm 1560) và
ESC ga (QuicRun 8BL150). Hai **miền servo**: KDS (cũ) hỏng giữa chừng → thay TowerPro (mới); hai servo
có ánh xạ lệnh→góc khác nhau → gắn cờ `domain_id` (0=KDS, 1=TowerPro). Bước ngoặt: bỏ link video không
dây WFB (hỏng ở tầm xa) → **đặt điện thoại Android lên xe** làm camera+recorder; khung & telemetry dùng
chung một đồng hồ → hết vấn đề đồng bộ; còn lại độ trễ chụp **δ_cam ≈ 100ms** được hiệu chỉnh.

**Đào sâu — "hai miền servo" là một thí nghiệm tự nhiên quý.** Vụ servo KDS hỏng là tai nạn, nhưng nó
tạo ra một tình huống đẹp: cùng một xe, cùng một thế giới, nhưng **hai ánh xạ lệnh→góc-lái khác nhau**.
Thay vì bỏ data cũ, gắn `domain_id` cho phép mô hình học **động lực học chung** (vật lý cảnh đổi ra sao
khi xe rẽ) trong khi vẫn phân biệt được "cùng lệnh steer=0.5 thì KDS quẹo khác TowerPro". Đây là nền
cho thí nghiệm transfer ở §11.3 — một đóng góp ngoài dự kiến.

**Vì sao một-đồng-hồ-chung là chìa khoá.** Trước đây (link không dây), khung hình tới PC ở một thời
điểm, telemetry tới ở thời điểm khác, hai đồng hồ lệch nhau → ghép cặp (ảnh, hành động) sai → mô hình
học nhầm "hành động này gây ra cảnh kia". Khi điện thoại vừa chụp ảnh vừa đọc telemetry trên **cùng
một đồng hồ**, ta biết chính xác "tại đúng lúc cảnh này xảy ra, lệnh là gì". Chỉ còn δ_cam (độ trễ từ
lúc cảm biến phơi sáng tới lúc callback trả ảnh) ≈ 100ms, được trừ ra khi đồng bộ.

---

## §7. Dữ liệu & Thống kê

**Report nói gì.** 209 phiên · 228.511 khung · 7,43 giờ (KDS 28 phiên/53k khung; TowerPro 181
phiên/175k khung). Ga trung vị 0,084 (thật, không ~0); 63% "gần thẳng"; 13.871 sự kiện rẽ; tốc độ trung
vị 1,05 m/s; 11,3% đứng yên. KDS gần "chỉ-lái" (ga ~hằng); TowerPro có ga biến thiên (kể cả lùi nhẹ).
Chia theo phiên 80/20 → 167 train / 42 val.

**Đào sâu — vì sao "chia theo PHIÊN, không theo KHUNG".** Nếu chia ngẫu nhiên theo khung, khung t vào
train và khung t+1 (gần như giống hệt) vào val → val "rò rỉ" thông tin từ train → điểm val đẹp giả
tạo (mô hình đã thấy gần như chính cảnh đó). Chia theo phiên đảm bảo **cả một đoạn lái** chỉ ở một
phía → val thật sự là "cảnh chưa từng thấy". Đây là điểm nghiêm túc về phương pháp.

**Đào sâu — vì sao 13.871 sự kiện rẽ lại được nhấn mạnh.** Nó phản bác trước một lời chê có thể có ở
§13: "xe lệch vì data không dạy cách lái hiệu chỉnh". Không — data **đầy** hành vi rẽ/hiệu chỉnh hai
phía. Thứ thiếu lúc *deploy* là khác: một **ảnh mục tiêu chỉ đường-về khi đã lệch** (xem §13.7), không
phải thiếu hành vi lái trong tập huấn luyện.

**Đào sâu — 11,3% đứng yên là một con số "gài bom" cho §13.4.** Nhớ nó: một phần đáng kể data là xe
đứng yên, và lúc đứng yên thì "lái không xoay cảnh" → liên quan trực tiếp tới bế tắc đứng yên.

---

## §8. Bộ mã hoá V-JEPA 2.1 đông cứng & Pipeline tiền-mã-hoá

**Report nói gì.** ViT-L 384 đông cứng tuyệt đối. Mỗi khung → lưới 24×24 = **576 token × 1024-D**, giữ
cả 576 (không pool). Tối ưu mấu chốt: **tiền-mã-hoá offline** — chạy V-JEPA một lần cho cả dataset, lưu
latent fp16, huấn luyện chỉ đọc latent → nhanh hơn ~50–100×. Dùng 384px vì đó là độ phân giải gốc của
encoder.

**Đào sâu — vì sao tiền-mã-hoá hợp lệ (không phải ăn gian).** Vì encoder **đông cứng**, latent của một
khung **không bao giờ đổi** trong suốt huấn luyện. Nên tính trước một lần rồi tái dùng là tương đương
hoàn toàn với tính lại mỗi epoch — chỉ khác tốc độ. Đây là điều khiến huấn luyện trên một GPU 16GB
khả thi: forward ViT-L 228k khung mỗi epoch sẽ mất nhiều ngày; đọc file latent thì vài phút.

**Đào sâu — "giữ 576 token" vs "mean-pool" — mầm mống của §13.** Khâu **điều khiển** giữ cả 576 token
(cần vị trí không gian để biết bẻ lái đâu). Nhưng khâu **định vị** lại **mean-pool** 576→1 vector để so
ảnh tổng thể. Chính lựa chọn mean-pool ở khâu định vị (mất bố cục không gian + nhạy sáng toàn cục) là
nguyên nhân chính của lỗi closed-loop. Ghi nhớ sự đối lập này — nó là trục chính của §13.

---

## §9. AC Predictor — Kiến trúc & Huấn luyện (đóng góp chính)

> File: `src/jepa_wm/models/vjepa2_ac_car.py` (lớp `VJEPA2ACCar`). Cấu hình triển khai `cd4`:
> `configs/model/vjepa_ac_car.yaml`.

### §9.1. Cấu trúc token & cơ chế

**Report nói gì.** Mỗi khung → nhóm `[action_t (3-D), state_t (12-D), patch_t (576)]` = **578 token**.
Mặt nạ **block-causal** cho token khung t chú ý mọi token khung ≤ t. Đầu ra tại vị trí patch của khung
t dự đoán **bản đồ patch khung t+1**. Ba phép chiếu Linear đưa action/state/patch về `P=512`, cộng
positional embedding, 12 lớp Transformer (LN → MHSA 8 đầu → residual → LN → MLP 512→2048→512 →
residual), rồi `Linear 512→1024` ra ẑ_{t+1}.

**Đào sâu — vì sao "trộn chung một bàn" action + state + patch.** Bằng cách biến cả hành động, trạng
thái, và hình ảnh thành **cùng một loại token 512-D**, cơ chế self-attention cho phép **patch token
"hỏi" action token**: "nếu lái thế này thì tôi (ô patch này) nên dịch về đâu?". Đó là cách hành động
tác động vào dự đoán hình ảnh — không cần mạch nối tay, attention tự học quan hệ.

**Đào sâu — block-causal mask làm gì & KHÔNG làm gì.** Nó chỉ quy định "ai được *nhìn* ai" (token khung
t không được nhìn tương lai t+1 → tránh gian lận). Trong cùng một khung thì các token nhìn nhau hai
chiều. Mã dựng mask (rút gọn):

```python
fr = torch.arange(L) // self.group          # token thứ i thuộc khung nào (group = 578)
allowed = fr[:, None] >= fr[None, :]         # khung i được nhìn khung j nếu i >= j
mask.masked_fill_(~allowed, float("-inf"))   # chỗ cấm → -inf → softmax = 0
```

⚠️ Quan trọng: mask **không** cho token biết *danh tính* (mình là khung mấy, loại gì, ô nào). Việc gán
danh tính là của **position embedding** (§9.x bên dưới).

### §9.2. Quy mô ≈ 39,2M tham số

**Report nói gì.** `pred_dim=512, depth=12, n_heads=8, num_tokens=576, action_dim=3, state_dim=12` →
**39.192.576 tham số** (chỉ predictor; encoder không tính), 12 lớp Transformer chiếm ~96%. Cố ý nhỏ hơn
~300M của Meta vì ít data (228k khung) + 576 token/khung đã rất nặng → predictor lớn dễ overfit; và phần
cứng chỉ 1×RTX 5070 Ti 16GB.

**Đào sâu — vì sao "nhỏ" lại là lựa chọn đúng.** Số tham số nên cân với lượng data. Với ~228k khung,
một predictor 300M sẽ có quá nhiều "chỗ trống" để học vẹt từng cảnh thay vì học quy luật chung → overfit.
Thêm nữa, mỗi khung đã 578 token; chuỗi T=4 là 2312 token — tự-chú-ý có chi phí bậc hai theo độ dài
chuỗi → rất nặng. 12 lớp/39,2M là điểm cân bằng giữa "đủ sâu để học động lực học" và "đủ nhỏ để không
overfit + chạy vừa 16GB".

### §9.x. POSITION EMBEDDING — đào sâu + code ⭐

**Vì sao cần.** Self-attention **hoán vị-bất biến**: xáo thứ tự token thì kết quả chỉ xáo theo, giá trị
không đổi → attention **không tự biết token ở đâu**. Nhưng vị trí quan trọng theo **3 nghĩa**:
1. **Khung nào** (thời gian) — patch khung 0 ≠ patch khung 3.
2. **Loại token gì** — slot 0 là *action*, slot 1 là *state*, 576 slot sau là *patch*.
3. **Ô patch nào** (không gian) — patch góc-trái-trên ≠ patch giữa, trong lưới 24×24.

(Block-causal mask chỉ lo nhân quả thời gian, **không** gán 3 danh tính này → cần position embedding.)

**Dạng được chọn: học được + PHÂN TÁCH (factorized), không phải RoPE.** Thay vì một bảng khổng lồ
`T×578` vector, ta tách thành **hai bảng nhỏ** rồi **cộng**:

```python
# Khai báo (__init__):
self.temporal_pos = nn.Parameter(torch.zeros(1, max_frames, 1, pred_dim))   # (1,16,1,512) ← theo KHUNG
self.token_pos    = nn.Parameter(torch.zeros(1, 1, self.group, pred_dim))   # (1,1,578,512) ← theo SLOT
nn.init.trunc_normal_(self.temporal_pos, std=0.02)
nn.init.trunc_normal_(self.token_pos,    std=0.02)
```

```python
# Cộng vào (_embed):
x = torch.cat([at, st, zt], dim=2)                  # (B, T, 578, 512)
x = x + self.temporal_pos[:, :T] + self.token_pos   # ⭐ TOÀN BỘ phép position embedding
```

Vị trí cuối của token tại (khung t, slot g) = `temporal_pos[t] + token_pos[g]`.

**Mẹo broadcasting (phần cốt lõi).** `x` shape `(B, T, 578, 512)`. Hai bảng có một chiều = 1:

| Tensor | Shape | Chiều "1" → broadcast |
|---|---|---|
| `temporal_pos[:, :T]` | `(1, T, **1**, 512)` | trục **slot** → cùng 1 vector cho cả 578 token trong MỘT khung; khác nhau giữa các khung → "khung mấy" |
| `token_pos` | `(1, **1**, 578, 512)` | trục **khung** → cùng 1 vector cho slot g ở MỌI khung; khác nhau giữa 578 slot → "loại token gì / ô patch nào" |

Tổng hai bảng → mỗi cặp (t, g) một vector **duy nhất**, mà chỉ tốn `16×512 + 578×512` tham số thay vì
`T×578` vector.

**`token_pos` đóng HAI vai cùng lúc:** slot 0 = vector phân biệt *action*, slot 1 = *state*; slot 2..577
= 576 vector khác nhau cho 576 patch. Vì patch trải phẳng theo raster (trái→phải, trên→dưới), 576 vector
này chính là **position embedding KHÔNG GIAN** của lưới 24×24.

> **Câu hỏi hay gặp:** "ViT đã có pos-emb riêng, sao predictor còn cần?" → Đầu ra latent là 576 vector
> "trơ"; khi đưa vào *một Transformer mới* (predictor), nó không biết thứ tự không gian nữa → phải tự
> gắn lại bằng `token_pos`.

**Khác Meta:** Meta dùng **3D-RoPE** (xoay theo (t,h,w), 0 tham số học, ngoại suy độ dài tốt). Ở đây
clip ngắn cố định (T=4) nên không cần ngoại suy → một bảng học được đơn giản là đủ (Bảng 2 report ghi
đúng lý do này).

### §9.3–9.4. So Meta & vì sao không dự đoán toàn bộ state

**Report nói gì.** Giống Meta: encoder đông cứng, patch token, đan xen [action,state,patch], block-
causal. Khác: state 12-D (IMU+tốc độ, không proprioception dưới-mm), action 3-D (steer/throttle/domain,
không phải Δ end-effector 7-D), pos-emb học-được (không RoPE), 12 lớp/39,2M (không ~300M), động lực học
bicycle (không phải pose cánh tay). Predictor **chỉ dự đoán bản đồ patch**, không dự đoán state 12-D.

**Đào sâu — vì sao không dự đoán state.** (1) IMU rất nhiễu (§14) → học state dễ học bậy; (2) lập kế
hoạch chỉ cần tốc độ + yaw, mà mô hình bicycle đã lo; (3) nếu dự đoán state rồi đưa ngược lại làm đầu
vào bước sau, **sai số state tích luỹ và bùng nổ** qua rollout nhiều bước. Triết lý: *"dự đoán ít hơn
nhưng giữ cái đáng tin"*.

### §9.5–9.6. Huấn luyện & đường cong loss

**Report nói gì.** Target: patch token được **LN theo từng token** (khớp `normalize_reps` Meta);
predict_residual=false (dự đoán absolute). Loss = **L1** (teacher-forcing 1 bước + **rollout 2 bước**).
AdamW, bf16, gradient checkpointing, batch 64, frame_stride 2 (~0,22s/bước). Chiến lược LR kiểu WSD:
base run cosine giảm 0,79→0,60 (epoch 9) rồi phẳng; mất điện giữa epoch 12; cooldown `cd4` LR→0 kéo val
xuống **0,569** (rollout@1/identity 0,744) = checkpoint triển khai.

**Đào sâu — vì sao có rollout-loss (chống "trôi").** Teacher-forcing chỉ phạt dự đoán 1 bước khi *được
cho token thật*. Nhưng lúc CEM chạy, predictor roll **nhiều bước bằng chính dự đoán của mình** → sai số
tích luỹ. Nếu chỉ huấn luyện teacher-forcing, mô hình giỏi 1 bước rồi trôi khi roll. `L_ro` (rollout 2
bước, có re-LN giữa các bước y như lúc plan) buộc nó **ổn định dưới tự-hồi-quy** — đúng chế độ CEM dùng.

**Đào sâu — vì sao L1 không phải MSE.** Latent có vài chiều biên độ lớn; MSE (bình phương) sẽ bị các
chiều đó chi phối. L1 cân bằng hơn và **trùng metric với năng lượng CEM** (`‖·‖₁`) → nhất quán giữa
huấn luyện và lập kế hoạch.

---

## §10. Lập kế hoạch: CEM + Động lực học xe

**Report nói gì.** CEM: lấy mẫu N chuỗi hành động ~N(μ,σ) trên H=4, roll qua predictor, chấm
`E=‖ẑ_final − z_goal‖₁`, giữ K elite, khớp lại (μ,σ), lặp; xuất hành động đầu (receding-horizon) + tiêm
5 ứng viên lái cố định trải đều. Bicycle model: tích phân `[x,y,heading,speed]`; `yaw_rate = k_yaw ·
steer · speed` → **speed=0 ⇒ lái không tạo yaw**.

**Đào sâu — CEM là "tối ưu hoá bằng tiến hoá nhẹ".** Không cần đạo hàm. Nó cứ: thử nhiều → giữ tốt nhất
→ kéo phân phối về phía tốt → thử lại. Sau vài vòng, μ hội tụ về vùng hành động tốt. 5 ứng viên lái cố
định trải đều `[−1..+1]` là để **chống kẹt cực tiểu địa phương**: nếu phân phối Gauss đang chụm nhầm
chỗ, các ứng viên rải đều vẫn có cơ hội bắt được đáy thật.

**Đào sâu — vì sao `speed=0 ⇒ không yaw` là một "quả bom hẹn giờ".** Công thức này đúng về vật lý (xe
đứng yên bẻ lái thì bánh quay nhưng thân không xoay). Nhưng hệ quả với CEM: khi xe dừng, **mọi góc lái
cho cùng một cảnh dự đoán** → mặt năng lượng theo lái **phẳng** → CEM mất phương hướng. Đây chính là cơ
chế "bế tắc đứng yên" ở §13.4 — và nó là lý do động lực học, **khác** với lý do descriptor ở §13.2.

---

## §11. TIER 1 — Động lực học offline

**Report nói gì.** Câu hỏi: predictor có thực học "hành động → đổi latent" không? Hai thước đo:
(1) `rollout@k/identity` < 1 (cd4: 0,744/0,703/0,697 — thắng baseline "cảnh đứng yên" ở mọi tầm);
(2) độ nhạy hành động (probe năng lượng): lái argmin đúng dấu **95%**, lệch trung vị **0,146**; ga 83%
"muốn tới". Transfer chéo servo: chỉ-TowerPro 1,073 → tiền-huấn-KDS-finetune 0,975 → **trộn 0,65**.

**Đào sâu — "collapse" (sụp latent) là bẫy gì.** Hai khung kề nhau gần như giống hệt (xe đi ~1m/s,
0,22s/bước). Một mô hình **lười** chỉ cần học "copy latent hiện tại sang khung kế" là đã đạt val-loss
rất thấp — mà **không học gì** về tác động của hành động. Val-loss đẹp nhưng mặt năng lượng **phẳng theo
hành động** → CEM vô dụng. Chia cho identity baseline **phơi bày** bẫy này: mô hình copy → tỉ số ≈ 1;
chỉ khi *thật sự dùng hành động* tỉ số mới < 1. Vì vậy `<1` là điều kiện **cần** nhưng chưa đủ — nên ta
đo thêm **độ nhạy hành động**, vốn là cái CEM thực sự dùng.

**Đào sâu — vì sao "đo từng trục riêng trước".** Ở Tier 1, khi đo độ nhạy lái thì *giữ ga = teacher*
(và ngược lại). Mục đích: **cô lập** xem mỗi trục có mang tín hiệu không. Nếu sau này (Tier 2, đo đồng
thời) hỏng mà từng trục riêng đều ổn, ta biết lỗi nằm ở *tương tác hai trục* chứ không ở từng trục.
Đây lại là tinh thần "tách để quy trách nhiệm".

**Đào sâu — transfer chéo servo nói lên điều gì.** Servo cũ KDS giàu dữ liệu lái. Khi trộn KDS+TowerPro
(với `domain_id`), mô hình học được **động lực học chung** (vật lý cảnh đổi khi rẽ) từ cả hai, rồi
`domain_id` chỉ việc tinh chỉnh "cùng lệnh thì servo nào quẹo bao nhiêu". Kết quả: trộn (0,65) thắng rõ
chỉ-TowerPro (1,073, thậm chí thua baseline vì quá ít data). Bài học: với data ít, **chia sẻ động lực
học chung** quan trọng hơn là tách riêng từng miền.

---

## §12. TIER 2 — Bộ lập kế hoạch open-loop chọn ĐỒNG THỜI (lái + ga)

**Report nói gì.** Câu hỏi: khi *thực sự để CEM lập kế hoạch* trên video thật (vòng lặp vẫn mở), nó có
chọn như người, và chọn **cả ga** không? Với mỗi khung: mục tiêu = bản đồ patch d=4 bước (~0,9s) phía
trước; quét lưới **15 lái × 9 ga = 135 tổ hợp**; argmin trên cả lưới. Kết quả (893 khung rẽ): lái đúng
dấu **94,2%**, lệch độ lớn **0,118**; ga muốn-tới **91,9%**, lệch ga **0,033**. → Planning khớp chuyên
gia cả dấu lẫn độ lớn, trên cả hai trục.

**Đào sâu — vì sao chọn d=4 (~0,9s) làm tầm mục tiêu.** Đây là một sự đánh đổi:
- d quá nhỏ (d=1, ~0,2s): cảnh gần như không đổi giữa hiện tại và mục tiêu → mọi hành động cho cảnh
  giống nhau → **contrast phẳng** → không phân biệt được hành động.
- d quá lớn (d=8): cảnh mục tiêu xa quá, gần như không còn chồng lấp cảnh hiện tại → cũng mất tín hiệu
  (đo được: contrast d=2 0,44 → d=8 0,27).
- d=4 là điểm ngọt: **đủ xa** để hành động lái tạo khác biệt cảnh đo được, **đủ gần** để còn chồng lấp
  mục tiêu.

**Đào sâu — vì sao "open-loop" KHÔNG chứng minh "tự lái".** Video đang phát lại lượt người lái → khung
kế **đã bị người cố định**. Mô hình chỉ *đề xuất* hành động trên cảnh đó; nó không thực sự điều khiển
khung kế. Nên Tier 2 đo "**nếu được chọn thì mô hình chọn giống người không**" — một câu hỏi sạch về
năng lực planning, tách hẳn khỏi vật lý closed-loop. Kết luận quan trọng: vì Tier 2 đạt, thứ hỏng ở
Tier 3 **không phải** "planner ngớ ngẩn".

---

## §13. TIER 3 — Closed-loop ngoài trời (chưa tự lái; phân tích cơ chế)

**Report nói gì.** Đóng vòng lặp thật: **bám nửa đầu, rồi lệch ra**. Tinh chỉnh siêu tham số chỉ *dời*
điểm lệch, không *xoá*. ~10 lần chạy, 0 lần tới đích → kết quả **định tính + cơ chế**. Nhiều nguyên
nhân: **chính** = khâu định vị (descriptor không bất biến ánh sáng/hướng, §13.2); thử nhiều biện pháp
đều chưa đủ (§13.3); bế tắc đứng yên (§13.4, đã vá); độ trễ suy luận (§13.5); cảm biến thô + bicycle
(§13.6).

### §13.2. Nguyên nhân chính A — descriptor định vị không bất biến

**Báo cáo nói gì.** Hệ thống dùng V-JEPA cho **hai khâu, hai metric**:

| Khâu | Metric | Độ bền |
|---|---|---|
| **Điều khiển (CEM)** | **L1 trên 576 patch token** (`‖P − z_goal‖₁`) | **BỀN** — nắng→mây đổi <5% |
| **Định vị (chọn ảnh mục tiêu kế)** | **cosine trên latent MEAN-POOLED** (576→1 vector 1024-D) | **SỤP** |

Bằng chứng: cùng-phiên-gần-thời → **66% tick** cos>0,3; dạy/chạy lệch ánh sáng → **0% tick** cos>0,3.
Đây **không** phải "V-JEPA kém" (cùng encoder đó, patch-L1 vẫn bền) mà là lỗi **lựa chọn descriptor**
(mean-pool + cosine nhạy ánh sáng toàn cục + hướng).

**Đào sâu — vì sao mean-pool + cosine lại sụp (cơ chế).** Mean-pool gộp 576 token thành 1 vector 1024-D
"trung bình toàn cảnh". Vector này bị chi phối bởi **thành phần chung lớn** ("đây là một cảnh công viên
ngoài trời sáng") — thành phần này gần như giống nhau ở mọi chỗ trong công viên → cosine giữa hai chỗ
*khác nhau* vẫn rất cao (bão hoà 0,94–0,97). Tệ hơn, khi ánh sáng đổi (nắng→mây), **cả vector xoay
cùng nhau** một góc lớn → cosine giữa ảnh-trực-tiếp và ảnh-mốc rớt mạnh, dù vẫn cùng một chỗ. Hai vấn
đề: (1) **bão hoà** (không phân biệt chỗ); (2) **nhạy sáng** (cùng chỗ khác giờ → không khớp).

### §13.2-bis. CÁC BIẾN THỂ DESCRIPTOR ĐÃ THỬ THAY COSINE GỐC ⭐ (bổ sung — report chưa mô tả)

> Đây là phần report **chưa** viết (§13.3 report chỉ nói chỉnh-ngưỡng / cùng-phiên / GPS-gate / quét-
> CEM). Thực tế trong code đã thử **nhiều biến thể descriptor** để chống bão-hoà + nhạy-sáng. Mỗi biến
> thể: **làm gì · vì sao · đo thế nào · cài ở đâu**. Phân biệt **đã deploy** (chạy trong
> `inference_loop.py`) vs **chỉ probe offline** (script đo, chưa đưa vào vòng chạy).

**Cách ĐO chung (phương pháp luận).** Có 3 script đo, tách hẳn khỏi closed-loop để "soi" descriptor:
- **`scripts/probe_reach.py`** — encode mọi ảnh trong một thư mục route (chụp tuần tự), in **ma trận
  cặp-đôi** (ảnh i vs ảnh j) cho từng metric. Metric **tốt** = đường chéo (i==j) tách rõ khỏi
  off-diagonal **và** đơn điệu theo `|i−j|` (ảnh kề nhau giống hơn ảnh xa). In kèm "hàng-xóm-gần-nhất
  có đúng là ảnh kề không: k/n" + "mean theo khoảng cách route". Đây là bench offline trả lời "cosine
  có bão hoà không / metric nào tách chỗ tốt".
- **`scripts/probe_route_sim.py`** — (1) phân tích cấu trúc route từ ảnh teach (per-subgoal `‖z_i − c‖`,
  ccos kề/xa, margin) + so sánh **các phép đo: cos thô / centered / bỏ-top-PC / whiten-shrink / patch-L1
  / seq-2**; (2) `--cross-sessions`: lấy frame người-lái-cũ (`data/raw_*`) có GPS rơi đúng xy subgoal +
  heading khớp → "live frame khác ngày" → đo ccos teach-vs-khác-ngày tại đúng mốc (đo domain-shift ánh
  sáng). **Kết quả then chốt:** mọi phép-đo-**1-frame** localize ±1 ≈ **random 15%** khi cross-lighting.
- **`scripts/probe_seqslam_lighting.py`** — đo **sequence-matching (SeqSLAM)** vs single-frame, chấm
  bằng **hình học**: localize-error = `‖query_xy[i] − ref_xy[matched_j]‖`, in median error (m) + %<tol
  per method × độ-dài-chuỗi Ls∈{1,5,10,20} (Ls=1 = baseline 1-frame). Câu hỏi-cổng: SeqSLAM có kéo
  %<tol từ ~15% lên >60% không?

Giờ là từng biến thể:

**(1) `cos` — cosine pooled THÔ (GỐC, đang deploy).**
- *Làm gì:* mean-pool 576 token → 1 vector 1024-D; L2-normalize; cosine = tích vô hướng.
- *Cài ở đâu:* `graph.localize` (`q = latent/‖latent‖; sims = Zn @ q`, `graph.py`); và nhánh route-tay
  mặc-định trong `inference_loop.py`. Trong `probe_reach.py`: `pn=normalize(pools); cos=pn@pn.T`.
- *Vấn đề:* bão hoà (park: 0,94–0,97 giữa các chỗ KHÁC nhau → "cosine nào cũng cao") + nhạy sáng.

**(2) `ccos` — CENTERED cosine (TRỪ-MEAN route) — đang deploy, mặc định từ 06-12.**
- *Làm gì:* lấy **mean của các vector pooled của TẤT CẢ subgoal trên route** (= thành phần chung "một
  ảnh trong chỗ này"), **trừ** nó khỏi mỗi vector, **rồi** mới cosine.
- *Vì sao:* bỏ thành phần chung → khuếch đại khác biệt: kề ~+0,5 / xa ~−0,4 (thay vì 0,89–0,99 tất). De-
  bão-hoà rẻ nhất.
- *Cài ở đâu:* `inference_loop.py` — `man_center = mean(_pools); man_vecs = [(p−man_center)/‖·‖]`; rồi
  `_mcos(i) = navn @ man_vecs[i]`. Trong `probe_reach.py`: `c = pools − pools.mean(0); cn=normalize(c);
  ccos = cn@cn.T`.
- *Hạn chế:* vẫn **coarse** (pooled → mất bố cục không gian) + vẫn **nhạy sáng** (centering trừ được
  cái chung *trong cùng route* nhưng không trừ được sự dịch sáng *khác buổi* giữa teach và run).

**(3) `ccos SPATIAL-token` — centered PER-PATCH, GIỮ không gian (`--pop-spatial`, deploy opt-in 06-14).**
- *Làm gì:* **KHÔNG pool** — giữ cả 576 patch. Center **theo từng vị-trí patch** (trừ mean-token-theo-
  vị-trí, lấy qua các subgoal → `man_tcenter` shape (576,1024)), normalize **từng patch**, rồi cosine
  từng patch và lấy **MEAN trên 576 patch**.
- *Vì sao:* mean-pool phá bố cục → hai cảnh **khác layout** vẫn pool ra vector giống (nguồn gốc bão
  hoà). Giữ spatial **đòi khớp CỤC BỘ** (layout phải trùng) → sắc hơn nhiều.
- *Cài ở đâu:* `inference_loop.py` — `man_tcenter = _toks.mean(0)`; `man_tvecs = normalize(_toks −
  man_tcenter, per-patch)`; view hiện tại `cur_tvecn = normalize(ctrl_tokens − man_tcenter, per-patch)`;
  `_mcos(i) = mean₅₇₆( cur_tvecn · man_tvecs[i] )`.
- *Lưu ý thực tế:* **thang cos KHÁC** mean-pool (biên độ thường hẹp hơn) → phải soi cột cos vài tick
  rồi chỉnh lại ngưỡng pop/reach.

**(4) `L1 patch-token (LN)` — energy h=0 (probe; chính là metric ĐIỀU KHIỂN).**
- *Làm gì:* `mean|Δ|` giữa patch token đã LN của ảnh hiện tại vs subgoal = **năng lượng CEM ở horizon 0**
  (không qua world model). Thấp = giống.
- *Vì sao:* giữ trọn cấu trúc không gian → kỳ vọng **tách vị trí tốt nhất**. Đây đúng là metric mà khâu
  điều khiển dùng — và report đo nó **bền sáng** (<5%). Nghịch lý của cả §13: metric tốt (patch-L1) đã
  có sẵn ở khâu điều khiển, nhưng khâu **định vị** lại đi dùng cosine-pooled.
- *Cài ở đâu:* `probe_reach.py` (`l1[i] = (toks − toks[i]).abs().mean((1,2))`, lower=better). (Trong
  vòng chạy, patch-L1 dùng cho **năng lượng CEM**, chưa được lắp thành metric *pop/localize* chính.)

**(5) `bỏ-top-PC` (−top1PC) — probe (`probe_route_sim.py`).**
- *Làm gì:* chiếu bỏ **thành phần chính lớn nhất** (top principal component) của các vector pooled rồi
  mới cosine. Top-1 PC thường = hướng "nhiễu chung" (ánh sáng toàn cục / "đây là cảnh chung").
- *Vì sao:* nếu PC đầu chính là phương nhiễu sáng, bỏ nó đi sẽ còn lại nội dung phân biệt chỗ.

**(6) `whiten-shrink` — probe (`probe_route_sim.py`).**
- *Làm gì:* **whitening** (khử tương quan + scale mỗi chiều về phương sai đơn vị) có **shrinkage** (co
  hồi quy hoá để ổn định), rồi cosine. Cân bằng các chiều để vài chiều phương-sai-lớn (sáng) không lấn
  át.

**(7) `seq-2` / `SeqSLAM` — sequence matching (probe `probe_route_sim.py` seq-2 + `probe_seqslam_lighting.py`).**
- *Làm gì:* thay vì khớp **một frame**, khớp **một CHUỖI frame liên tiếp** dọc một đường chéo (ràng buộc
  vận tốc) trong ma trận khác-biệt, có **local-contrast-normalization**. Ls ∈ {1,5,10,20}; Ls=1 =
  baseline 1-frame.
- *Vì sao:* đây là **fix chuẩn trong literature** cho bất-biến-điều-kiện (ánh sáng): local-contrast-norm
  triệt tiêu "cả route dịch cùng nhau khi đổi sáng"; ràng buộc chuỗi loại bỏ alias 1-frame.
- *Đo thế nào:* build difference matrix D[query_i, ref_j] từ descriptor → norm → tìm chuỗi chéo → chấm
  hình học (localize-error mét, %<tol). Đây là **ứng viên fix mạnh nhất** cho cross-lighting, nhưng là
  hướng probe (chưa lắp vào vòng deploy trước deadline).

**Tóm tắt biến thể (làm gì / trạng thái):**

| # | Biến thể | Ý tưởng cốt lõi | Trạng thái |
|---|---|---|---|
| 1 | cos pooled thô | mean-pool → cosine | deploy (gốc) — **bão hoà + nhạy sáng** |
| 2 | centered (ccos) | trừ mean route → cosine | **deploy mặc định 06-12** — đỡ bão hoà, vẫn coarse/nhạy sáng |
| 3 | centered SPATIAL | giữ 576 patch, center per-patch, mean per-patch cos | **deploy opt-in `--pop-spatial`** — sắc hơn (khớp layout) |
| 4 | patch-L1 (energy h=0) | `mean\|Δ\|` token LN, giữ spatial | probe — tách chỗ tốt, **bền sáng** |
| 5 | bỏ-top-PC | chiếu bỏ PC1 (phương sáng) | probe |
| 6 | whiten-shrink | whitening + shrinkage rồi cosine | probe |
| 7 | seq-2 / SeqSLAM | khớp CHUỖI + local-contrast-norm | probe — fix literature cho cross-lighting |

**Kết quả tổng (vì sao tất cả vẫn chưa đủ trong deadline).** `probe_route_sim --cross-sessions` đo:
**mọi phép-đo-1-frame** (ccos / −top1PC / patch-L1) khi cross-lighting đều rớt về ~**random 15%**
(localize ±1). Tức: centering / bỏ-PC / whiten / giữ-spatial đều **giảm bão-hoà** (tốt cho phân biệt
chỗ *cùng buổi*) nhưng **không giải quyết được nhạy-sáng** *khác buổi* — vì đó là một dịch miền sâu hơn
mà một phép biến đổi tuyến tính thủ công không xoá nổi. SeqSLAM (chuỗi) là hướng hứa hẹn nhất nhưng chưa
kịp lắp + kiểm chứng closed-loop. → Củng cố **kết luận của report**: cách sửa căn cơ là **học một
descriptor bất biến ánh sáng/hướng** (đầu nhỏ trên V-JEPA đông cứng, huấn luyện chéo-phiên — §16), không
phải tiếp tục chỉnh tay biến thể cosine.

### §13.3. Các biện pháp khác (report đã liệt kê)
Chỉnh **ngưỡng cosine** (chỉ dời *khi nào* sụp, không *có sụp hay không*); **dạy & chạy cùng phiên gần
thời** (chạy được nhưng bó vào cửa sổ thời gian hẹp); **pop cổng-GPS** (GPS 1Hz/nhiễu 0,44m → kích bừa);
**quét tham số CEM** (dời điểm bứt ra, không cứu được mặt phẳng khi cosine đã sụp).

### §13.4. Bế tắc đứng yên (đã vá) — lý do ĐỘNG LỰC HỌC, khác A
Mỗi tick CEM ~0,5–1s → xe **bò–dừng–bò–dừng**. Khi dừng (`speed≈0`): `yaw_rate=k_yaw·steer·speed` → lái
không xoay cảnh → mọi góc lái cùng một cảnh → **contrast E(steer) sụp** (đo: chạy 0,335 → đứng yên
0,088, ×3,8). Bẫy: hộp ga `[0,0.10]` chứa vùng-chết-ma-sát `[0,0.06)` → chọn ga thấp → không lăn →
phẳng → lái rác → đứng im → lặp. **Vá:** sàn ga `TMIN=0,07`. Sau vá xe chạy nhưng **vẫn lệch ở A** → A
mới là nút chính. **Phân biệt với A:** B phẳng vì *xe đứng yên* (động lực học); A phẳng vì *mục tiêu
không phân biệt được* (descriptor).

### §13.5–13.6. Độ trễ suy luận & trạng thái thô
- **§13.5 — lái mù:** ViT-L phải chạy trên PC → khứ hồi TCP 0,5–5,5s/quyết định → xe lái mù theo lệnh
  cũ. Hệ quả: lập kế hoạch trên **trạng thái cũ 0,5–1,5s** (ở 1m/s = lệch 0,5–1,5m); vòng lặp không
  tuần hoàn → mismatch `dt` bicycle tích luỹ sai hướng; khi A đã đẩy lệch, mỗi chu kỳ chết = thêm
  0,5–1m trôi.
- **§13.6 — trạng thái thô:** khác cánh tay Meta (proprioception dưới-mm chính xác), xe có tốc-độ-GPS-
  1Hz (trễ/mượt), hướng-IMU (la bàn nhiễu gần motor), không vị trí tuyệt đối, bicycle giả định không
  trượt lốp/đất phẳng (xe thật trên cỏ/sỏi trượt nhiều) → CEM roll trạng-thái-sai qua mô-hình-sai.

### §13.7. Vì sao không tự phục hồi khi đã lệch (hệ quả của A)
Teach chỉ thu ảnh mục tiêu **dọc một đường** (xe ở giữa tuyến). Khi xe lệch khỏi hành lang → ảnh trực
tiếp rơi vào vùng **chưa từng thu làm mốc** → cosine tới mốc kế rớt (đúng cơ chế A) → **không có mục
tiêu hợp lệ để lái về**. Lưu ý: AC predictor **không thiếu** hành vi hiệu chỉnh (13.871 sự kiện rẽ);
thứ thiếu là **ảnh mục tiêu chỉ-đường-về khi off-route** — hệ quả của dạy-một-lần-giữa-đường + sụp A.

---

## §14. Đánh giá dữ liệu IMU & vì sao không dự đoán toàn bộ next-state

**Report nói gì.** State 12-D = 10 kênh IMU (gyro 3 + accel 3 + rotvec 3) + tốc độ GPS. Quan sát: rất
nhiễu & phụ thuộc cách gắn (điện thoại buộc vào xe → trộn rung khung/xóc/cộng hưởng giá); GPS 1Hz phải
nội suy (trễ/mượt); rotvec ổn cho pitch/roll nhưng yaw trôi + la bàn ngoài trời kém. **Chỉ `speed` và
`gz` (yaw-rate) thực sự đáng tin** cho điều khiển.

**Đào sâu — vì sao điều này biện minh cho lựa chọn §9.4.** Nếu state đã nhiễu mà còn bắt predictor *dự
đoán* state rồi đưa ngược lại làm đầu vào bước sau, ta đang chồng nhiễu lên nhiễu qua mỗi bước rollout →
bùng nổ. Hợp lý hơn: predictor **chỉ dự đoán hình ảnh** (cái có tín hiệu sạch nhờ encoder mạnh), còn
trạng thái tương lai để **mô hình bicycle** sinh ra (chỉ cần speed + yaw, đúng 2 chiều đáng tin). Đây là
hiện thân cụ thể của triết lý "dự đoán ít hơn nhưng giữ cái đáng tin".

**Hệ quả phần cứng:** thay IMU điện thoại bằng **BNO055** (9 trục, sensor-fusion phần cứng) sẽ cho
orientation/gyro ổn định hơn hẳn → token state sạch hơn (§16).

---

## §15. Hạn chế

**Report nói gì.** (1) Closed-loop ~10 run, 1 môi trường, 0 tới đích → định tính, không thống kê lớn;
(2) descriptor định vị nhạy sáng/hướng, cần descriptor học được; (3) GPS 1Hz/0,44m → chỉ cổng pop thô;
(4) IMU nhiễu → chỉ speed+yaw đáng tin; (5) encoder không chạy on-device → trễ CEM 0,5–5,5s; (6) biên
offline khiêm tốn (rollout@1 0,744) → mức báo cáo/workshop, không SOTA.

**Đào sâu — đọc các hạn chế này như một "bản đồ rủi ro".** Quan trọng: các hạn chế đã được **phân tầng
nguyên nhân** (định vị > đứng yên > độ trễ > cảm biến), nên biết **sửa cái nào trước**: descriptor học
được (gốc của #2, và là nút chính của Tier 3) > BNO055 (gốc #4) > on-device/RTK (gốc #5,#3). Việc thành
thật ghi "không SOTA, 0 lần tới đích" là điểm cộng về liêm chính khoa học — báo cáo bán *phân tích*,
không bán *thành tích*.

---

## §16. Hướng phát triển

**Report nói gì.** (1) BNO055 thay IMU; (2) **descriptor học được bất biến sáng/hướng** (đầu nhỏ trên
V-JEPA đông cứng, huấn luyện chéo-phiên — dataset 181 phiên ĐÃ có cặp cùng-chỗ-khác-thời) = sửa gốc
nguyên nhân A; (3) token-shift augmentation ("DAVE-2 cho latent", khuếch đại đáp ứng lái-về 3,4–5,4×
offline, nhưng là proxy không renderer → tắt mặc định); (4) mô phỏng 3DGS; (5) RTK GPS 1–2cm; (6) thí
nghiệm phụ đồ thị ảnh topo (offline ~2m, khó điều khiển thật → chốt chuỗi tuyến tính subgoal).

**Đào sâu — hạng mục (2) nối thẳng với §13.2-bis.** Cả 7 biến thể descriptor thủ công (cosine/centered/
spatial/bỏ-PC/whiten/SeqSLAM) đều cho thấy: biến đổi tuyến tính tay **không xoá nổi** dịch-sáng-khác-
buổi. Lối ra đúng là **học** một phép chiếu bất biến từ chính data (đã có sẵn cặp cùng-chỗ-khác-thời để
làm cặp dương/âm cho contrastive). Đây là bài học rút ra từ chuỗi thử nghiệm descriptor — nên đưa vào
report như mạch dẫn từ "đã thử gì → vì sao chưa đủ → hướng đúng".

---

## §17. Kết luận

**Report nói gì.** V-JEPA 2.1 đông cứng cho biểu diễn **đủ tốt** để: (Tier 1) AC predictor 39,2M thắng
identity ở mọi tầm + nhạy cả hai trục + transfer chéo servo; (Tier 2) planner chọn ĐỒNG THỜI lái+ga khớp
người ~94% đúng hướng, gần độ lớn; nhưng (Tier 3) closed-loop ngoài trời **lệch** — nút chính là **khâu
định vị** (descriptor pooled-cosine không bất biến), **không** phải biểu diễn. Trình bày như **một thí
nghiệm dòng V-JEPA 2 trên robot di động** + **phân tích hỏng có cơ chế**.

**Đào sâu — một câu chốt để nhớ.** Với *cùng một biểu diễn mạnh*, khoảng cách giữa "dự đoán latent tốt
+ planning offline khớp chuyên gia" và "lái thật ngoài trời" **không** nằm ở mô hình thế giới, mà ở
**khả năng định vị bền vững** dưới dịch miền (ánh sáng/hướng) — cộng thêm ràng buộc độ-trễ + cảm-biến.
Đó là đóng góp thật: chỉ đúng chỗ cần sửa.

---

## §18. Phụ lục (tham chiếu nhanh)

- Checkpoint triển khai: `checkpoints/vjepa_ac_car_cd4/vjepa_ac_car/best.pt` — ViT-L 384, state 12-D,
  predictor depth12/pred_dim512/8 đầu/39,2M, action 3-D, `auto_steps 2`, `predict_residual false`.
- Đếm tham số (1 dòng):
  `python -c "import torch;sd=torch.load('.../best.pt',weights_only=False)['model'];print(sum(v.numel() for v in sd.values()))"`
- Đo Tier 1: `scripts/eval_ratio_ac.py`, `scripts/probe_energy.py --turn-only -d 4 --with-throttle`.
- Đo Tier 2: `scripts/demo_precompute.py <session> -d 4`, `scripts/plot_steer_tracking.py`.
- Đo descriptor (§13.2-bis): `scripts/probe_reach.py --dir <route>`, `scripts/probe_route_sim.py --route
  <r> --cross-sessions 3`, `scripts/probe_seqslam_lighting.py --auto-pairs 3`.
- Đo bế tắc đứng yên (§13.4): `scripts/probe_speed_confound.py -d 4 --n-windows 200`.

## §19. Tài liệu tham khảo
Giữ nguyên như report gốc (V-JEPA [1], V-JEPA 2 / 2.1 + 2-AC [2], LeCun path [3], I-JEPA [4], ViNG [5],
CEM [6], AdamW [7], bicycle model [8], BNO055 [9]).

---

## Phụ lục B — Từ điển thuật ngữ nhanh

| Thuật ngữ | Nghĩa ngắn |
|---|---|
| **Latent / patch token** | 576 vector 1024-D mã hoá một khung (bản đồ đặc trưng 24×24). |
| **Frozen encoder** | V-JEPA đông cứng, không huấn luyện; chỉ "nhìn". |
| **AC Predictor** | ~39,2M tham số học "hành động → đổi latent"; đóng góp chính. |
| **Block-causal mask** | Khung t chỉ được nhìn khung ≤ t (không nhìn tương lai). |
| **Position embedding** | Vector gắn danh tính (khung nào / loại token / ô patch nào). |
| **temporal_pos / token_pos** | 2 bảng pos-emb phân tách (theo khung / theo slot); cộng broadcasting. |
| **Energy E** | `‖ẑ − z_goal‖₁`; thấp = hành động đưa cảnh gần mục tiêu. |
| **Contrast** | Độ sâu thung lũng năng lượng; ≈0 = phẳng = CEM mất phương hướng. |
| **CEM** | Lập kế hoạch: lấy mẫu–chấm–giữ elite–lặp; xuất hành động đầu. |
| **Bicycle model** | Động học xe; `yaw_rate = k_yaw·steer·speed`. |
| **rollout@k / identity** | Tỉ số đo predictor có thắng "cảnh đứng yên"; <1 = thắng. |
| **cos / ccos / spatial-ccos** | cosine pooled thô / centered / centered giữ-spatial (các biến thể định vị). |
| **bỏ-top-PC / whiten / SeqSLAM** | Các biến thể descriptor probe-offline chống nhạy-sáng. |
| **cos-dropout** | cosine định vị sụp <0,1 → mất mục tiêu (nguyên nhân A). |
| **Domain (servo)** | KDS (cũ, giàu lái) vs TowerPro (mới, giàu ga); `domain_id` phân biệt. |
| **δ_cam** | Độ trễ chụp camera ≈100ms, hiệu chỉnh khi đồng bộ. |

## Phụ lục C — Bản đồ file
- AC Predictor + position embedding: `src/jepa_wm/models/vjepa2_ac_car.py`
- Cấu hình triển khai (cd4): `configs/model/vjepa_ac_car.yaml`
- Huấn luyện: `src/jepa_wm/engine/train_ac_car.py`
- CEM + động lực học: `src/jepa_wm/planning/{cem.py, dynamics.py}`
- Định vị (graph): `src/jepa_wm/nav/graph.py`; vòng chạy thật: `scripts/inference_loop.py`
- Probe descriptor: `scripts/{probe_reach,probe_route_sim,probe_seqslam_lighting}.py`
- Probe Tier 1/2 & đứng yên: `scripts/{probe_energy,eval_ratio_ac,demo_precompute,probe_speed_confound}.py`
