# BÁO CÁO — World Model Hành-động-điều-kiện dựa trên V-JEPA 2.1 cho Xe RC (bản prose)

*Bản văn xuôi để dán thẳng vào Word. Mọi con số đều tái lập được bằng script trong repo (xem báo cáo chi
tiết `2_REPORT_FULL.md` §Phụ lục). Placeholder: `[Họ tên]`, `[MSSV]`, `[Lớp/Môn]`, `[GVHD]`.*

---

## Tóm tắt (Abstract)

Chúng tôi nghiên cứu việc dùng một encoder video nền-tảng đóng băng — **V-JEPA 2.1 ViT-L 384** — làm biểu
diễn thị giác cho một **world model hành-động-điều-kiện** trên một **xe RC di động**, rồi dùng **CEM
planning** để cho xe **lặp lại một tuyến đã được dạy** (teach & repeat): người lái tay đi hết tuyến một
lần và hệ thống lưu lại chuỗi ảnh-mốc; khi chạy lại, tại mỗi bước model so ảnh hiện tại với ảnh-mốc kế tiếp
và chọn lái/ga để đi tới đó. Encoder được giữ đóng băng hoàn toàn; chúng tôi chỉ huấn luyện một **AC
Predictor** nhỏ (**~39 triệu tham số**, đếm trực tiếp từ checkpoint) học "hành động nào gây thay đổi hình
ảnh nào" trong không gian latent.

Kết quả được trình bày theo **ba tầng trung thực**. **Tầng 1 (offline, ✅):** AC predictor vượt baseline
"đứng yên" (identity) ở mọi horizon (rollout@1 = 0.744), có độ nhạy hành động đo được ở **cả hai trục** lái
và ga, và cho thấy **transfer chéo-domain-servo** có lợi. **Tầng 2 (open-loop, ✅):** trên video held-out,
planner chọn **joint cả lái lẫn ga**, lái **khớp dấu người ~94%** ở khúc quẹo và ga tự chọn muốn-tiến ~92%
(median +0.075 ≈ người +0.090). **Tầng 3 (closed-loop ngoài trời, ❌):**
hệ thống bám tuyến tốt ở nửa đầu route rồi bung ra lề; phân tích định lượng tách được **ba nguyên nhân cộng
hưởng** — descriptor V-JEPA không bất-biến-sáng, chế-độ-đứng-yên làm phẳng landscape năng lượng, và thiếu
dữ liệu lateral-recovery. Đây là **đánh giá đầu tiên của họ V-JEPA 2 trên một robot di động** và một
**negative finding trung thực, có cơ chế**, kèm đính chính minh bạch các kết luận trung gian từng sai.

---

## 1. Giới thiệu

Điều hướng bằng thị giác cho robot di động theo lối truyền thống dựa vào bản đồ hình học. Một hướng thay thế
gần đây là học biểu diễn tự-giám-sát rồi lập kế hoạch ngay trong không gian latent: thay vì xây bản đồ 3D,
ta học một *world model* dự đoán "hành động nào gây ra thay đổi hình ảnh nào" và tìm chuỗi hành động đưa
quan sát hiện tại về quan sát-mục-tiêu. V-JEPA học đặc trưng bằng *feature prediction* trong không gian biểu
diễn thay vì tái tạo pixel, tránh lãng phí dung lượng mô hình vào chi tiết pixel; bản 2.1 (ViT-L distilled
từ ViT-G, 384px) bổ sung Dense Predictive Loss cho đặc trưng patch chất lượng cao. Meta đã chứng minh
V-JEPA 2-AC (action-conditioned) cho phép planning **trên cánh tay robot**. Câu hỏi tự nhiên của chúng tôi:
liệu biểu diễn này có dùng được cho một robot **di động, ngoài trời**, với động lực học và domain-shift thật?

Đóng khung cho môn Computer Vision, bài toán gồm: biểu diễn thị giác từ một foundation model đóng băng; so
khớp ảnh trong latent để định vị và lập kế hoạch điều khiển; và độ bền của biểu diễn dưới domain-shift thật
(ánh sáng, giờ, góc nhìn) — chính là tâm điểm của phần phân tích thất bại. Vì encoder ViT-L cần GPU, không
chạy được trên điện thoại, suy luận phải qua PC. Sau vài ngày tinh chỉnh closed-loop ngoài thực địa mà chẩn
đoán cho thấy thất bại nằm ở chế-độ-điều-khiển, dữ liệu và descriptor chứ không phải ở tham số, chúng tôi
dừng thử nghiệm thực địa và chốt phần offline + kiểm chứng planner open-loop, trình bày closed-loop như một
negative finding được phân tích kỹ.

---

## 2. Công trình liên quan

Báo cáo giữ phần liên quan gọn có chủ ý, tập trung vào world model và teach & repeat. **V-JEPA / V-JEPA 2 /
2.1** là nền tảng học self-supervised bằng feature prediction. **V-JEPA 2-AC** của Meta — interleave
`[action, state, patch]` mỗi frame, predictor block-causal, CEM planning với năng lượng `‖P − z_goal‖₁` —
là **kiến trúc tham khảo** mà AC Predictor của chúng tôi dựa vào (so sánh giống/khác/vì-sao ở §3.4); Meta
chỉ thử trên cánh tay robot với cảnh bàn cố định. Từ **ViNG** (điều hướng bằng goal ảnh) chúng tôi mượn ý
tưởng "đi tới ảnh-mục-tiêu" cho teach & repeat; phần đồ-thị-ảnh topological của ViNG chỉ được chúng tôi thử
nghiệm phụ và không dùng làm hệ chính (§10). Các nhánh thử-nhanh khác (world model pixel-JEPA end-to-end,
place recognition theo chuỗi) không tham gia hệ chính và chỉ được nêu như hướng tương lai.

---

## 3. Phương pháp

### 3.1. Hệ thống phần cứng & cách thu thập dữ liệu (mô tả trước kiến trúc)

Hệ thống vật lý gồm một xe RC địa hình với một **ESP32-S3** điều khiển hai cơ cấu: servo lái TowerPro MG946R
(GPIO5, PWM 1000–2000µs, tâm 1560µs) và ESC Hobbywing QuicRun 8BL150 (GPIO6). Một chi tiết quan trọng cho
phần kết quả là dữ liệu được thu bằng **hai loại servo khác nhau** — KDS (cũ) và TowerPro (mới) — có ánh xạ
lệnh→góc-lái khác nhau, nên chúng tôi coi là hai "domain" điều khiển và gắn `domain_id` vào input model.

Ban đầu chúng tôi dùng một camera truyền H.265 không dây 5.8GHz về PC, nhưng link này vỡ ở tầm xa (~50m: vỡ
ảnh, trễ phình 92→310ms). Vì vậy chúng tôi **pivot: đặt một điện thoại Android (Samsung A42) lên xe** làm
camera ultrawide kiêm máy ghi; điện thoại đọc telemetry ESP32 qua USB, lưu frame + action + telemetry +
GPS + IMU. Vì frame và telemetry dùng chung một đồng hồ điện thoại, các vấn đề lệch clock biến mất; chỉ còn
độ trễ chụp camera δ_cam ≈ 100ms được ghi mỗi frame và hiệu chỉnh khi đồng bộ. Xe được lái tay bằng FlySky
i-BUS trong lúc ghi; bước `sync.py` ghép mỗi frame với hành động đúng thời điểm cảnh bằng nội suy telemetry
50Hz và xuất `actions_synced.csv` + `imu_synced.csv`. GPS điện thoại chỉ đạt ~1Hz với nhiễu vị trí trung vị
0.44m, nên GPS chỉ đủ làm cổng để pop ảnh-mốc, không đủ để giữ làn theo mét.

### 3.2. Dữ liệu & thống kê

Toàn bộ thống kê được quét lại trực tiếp từ `data/raw_*` bằng `scripts/dataset_stats.py`. Tập dữ liệu gồm
**209 session, 228,511 frame, tương đương 7.43 giờ** lái thật (KDS 28 session / 1.73 giờ; TowerPro 181
session / 5.71 giờ), thu ở ~8.5 fps. Phân bố hành động cho thấy throttle median 0.084 (ga thật, không phải
0), 63% thời gian đi gần-thẳng (|steer|<0.15) với 13,871 sự kiện quẹo, tốc độ median 1.05 m/s, và 11.3%
frame ở trạng thái đứng-yên (speed<0.06) — con số cuối liên quan trực tiếp tới phân tích lỗi ở §6. Dữ liệu
KDS có throttle gần như hằng (~7.5%, gần "steering-only"), nên chúng tôi thu thêm mẻ TowerPro với throttle
biến thiên để model có tín hiệu học chiều ga. Split tái lập được (seed 0, session-level 80/20) cho train 167
/ val 42 session, cố định cho mọi đánh giá. Báo cáo kèm 5 biểu đồ: phân bố steering/throttle/speed, độ dài
từng session, và phủ thời gian thu theo giờ.

### 3.3. Encoder đóng băng và một đo lường về tốc độ

Encoder V-JEPA 2.1 ViT-L 384 được giữ **đóng băng tuyệt đối**; chúng tôi encode từng frame thành 576 patch
token, mỗi token 1024 chiều, và pre-encode toàn bộ dataset offline một lần để khi huấn luyện chỉ đọc latent
(nhanh hơn ~50–100 lần). Một câu hỏi thiết kế là liệu latent single-frame có mang thông tin tốc độ hay
không. Chúng tôi **đo lại đàng hoàng** bằng `scripts/measure_speed_r2.py`: mean-pool patch map mỗi frame
thành vector 1024 chiều, hồi quy ridge để dự đoán tốc độ GPS, **fit trên session train và báo R² trên
session VAL held-out**. Kết quả là **R²(speed) ≈ +0.30 held-out** (train R² 0.72): latent **có** mang một
phần tín hiệu tốc độ nhưng **yếu**, chỉ giải thích khoảng 30% phương sai, nhiều khả năng qua manh mối gián
tiếp (motion-blur khi đi nhanh, bối cảnh nơi xe hay chạy nhanh) chứ không phải đo vận tốc trực tiếp — hợp lý
vì encoder chạy image-path từng-frame. Đây là một **đính chính quan trọng**: một ghi chú cũ ghi "R²=−1.1, mù
vận tốc hoàn toàn" là sai và không tái lập được. Vì tín hiệu tốc độ trong ảnh yếu và không đáng tin, chúng
tôi vẫn bơm tốc độ vào model qua **state token** (GPS speed) cho chắc.

### 3.4. AC Predictor — kiến trúc tham khảo và phép tính tham số

Với mỗi frame, AC Predictor xếp các token thành nhóm `[action_t, state_t, patch_t(1..576)]` (578 token) và
dùng một transformer **block-causal** để token ở frame t chỉ nhìn được token ở frame ≤ t; đầu ra ở vị trí
patch của frame t dự đoán patch map của frame t+1. Đây là **kiến trúc tham khảo từ V-JEPA 2-AC**, không phải
một "port trung thực": chúng tôi giữ những phần cốt lõi (encoder đóng băng, interleave action+state+patch,
attention block-causal, dự đoán latent frame kế) nhưng điều chỉnh có lý do cho xe. State của xe là IMU 10-D
cộng hành-động-bước-trước (12-D) thay cho pose tay máy 7-D, vì xe không có proprioception sub-mm và prev-
action giúp model biết "đang giữ lệnh gì"; action là `[steer, throttle, domain_id]` 3-D thay cho delta 7-D;
positional embedding học được thay cho 3D-RoPE; và động học cho CEM là bicycle-model fit từ data xe thay cho
`compute_new_pose` của tay máy.

Về quy mô, **đếm trực tiếp từ checkpoint triển khai (`cd4`) cho 39,192,576 tham số huấn luyện ≈ 39.2M**
(chỉ predictor; encoder đóng băng không tính). Cấu hình là pred_dim 512, depth 12, 8 heads, num_tokens 576.
Phân rã: mỗi lớp Transformer (d_model 512, feed-forward 2048, pre-LN) có 3,152,384 tham số, nhân 12 lớp =
37,828,608 (96.5% tổng); phần còn lại là `patch_embed` 524,800, `head` 525,312, `token_pos` 295,936, cùng
`action_embed`/`state_embed`/`temporal_pos`/`norm` nhỏ. Đây là một đính chính: các bản nháp trước ghi "~26M"
là sai. Chúng tôi cố ý giữ predictor nhỏ hơn nhiều so với ~300M của Meta vì dataset chỉ ~228k frame và 576
token rất nặng, predictor quá lớn dễ overfit.

Một câu hỏi tự nhiên: vì sao không cho predictor dự đoán luôn toàn bộ next-state 12-D? Có bốn lý do. Thứ
nhất, predictor được thiết kế là một **visual-latent predictor** — nó dự đoán patch map, không có head cho
state 12-D. Thứ hai, **dự đoán full IMU state rất khó**: các kênh accel/gyro/rotvec rất nhiễu, phụ thuộc mặt
đất/rung/bump/mount, và với dữ liệu ít rất dễ học sai hoặc overfit. Thứ ba, **planning chỉ cần phần state có
tác động lớn tới chuyển động** — tốc độ và yaw/turning — và phần này đã được bicycle-model lo, không cần
predictor đoán lại. Thứ tư, **nếu cố dự đoán full state rồi feed lại, sai số state có thể nổ nhanh hơn** khi
rollout nhiều bước. Vì vậy chúng tôi chọn triết lý "dự đoán ít nhưng phần nào còn tin được". (Đánh giá chất
lượng IMU và hướng thay bằng cảm biến BNO055 được bàn ở §7 và §10.)

### 3.5. Lập kế hoạch: CEM, động học và policy prior

Để chọn hành động, một CEM planner roll các chuỗi action ứng viên qua AC predictor và chấm năng lượng L1 từ
latent dự đoán cuối tới latent goal, theo lối receding-horizon (horizon 4, chỉ áp action đầu). Để elite bắt
được đáy toàn cục, mỗi iteration chèn thêm 5 ứng viên steer cố định trải đều [−1,1]. Trạng thái tương lai
trong khi roll được tích phân bằng một bicycle-model với hệ số fit từ data thật (`k_thr=1.588, k_drag=0.078,
k_yaw=0.088`); một điểm vật-lý quan trọng là `yaw = k_yaw·steer·speed`, nên khi speed=0 thì lái không sinh
yaw — gốc rễ của hiện tượng landscape phẳng ở §6. Về độ trễ, search dày (256 mẫu/2 vòng) tốn tới ~5.5s mỗi
quyết định, trong khi 32/1 chỉ ~0.5s với chất lượng tương đương, nên chúng tôi chốt 32/1.

---

## 4. TẦNG 1 — Kết quả đánh giá Offline (✅)

Câu hỏi của tầng này là predictor có thực sự học được "action → đổi latent" hay không, độc lập với chuyện
đóng vòng. Thước đo quyết định **không** phải val loss đơn lẻ (bị lừa bởi latent collapse) mà là tỉ số
**rollout@k / identity** so với baseline "đoán frame sau y hệt frame trước". Checkpoint triển khai cd4 đạt
0.744 / 0.703 / 0.697 ở horizon 1/2/3, tức thắng baseline ổn định ở mọi horizon. Một kết quả đáng chú ý là
**transfer chéo-domain-servo**: huấn luyện chỉ trên TowerPro thì eval TowerPro lại thua identity (1.073),
nhưng huấn luyện trộn cả KDS và TowerPro thì eval TowerPro xuống 0.65 — dữ liệu của servo khác giúp học động
học chung, và `domain_id` cho phép trộn mà không lẫn lộn ánh xạ lệnh→góc.

Để kiểm tra model có "đọc" được hành động không, chúng tôi quét năng lượng quanh từng trục action. Ở trục
lái, argmin năng lượng đúng dấu góc cua **96%** (98/102 cửa sổ quẹo) với contrast 0.413; ở trục ga, model
nhất quán muốn tiến (81% > 0) với contrast 0.298 và "muốn" ga +0.094 ≈ trung vị data 0.084. Như vậy model
không hề "đánh lái yếu" offline mà có đáy năng lượng rõ và đúng phía ở **cả hai trục**. Contrast tụt theo cự
ly target (d2 0.44 → d8 0.27), gợi ý nên đặt mốc gần và dạy dày. Một ablation âm xác nhận lựa chọn cấu hình:
tăng `auto_steps` lên 3 làm dự đoán multi-step tốt hơn nhưng action-sensitivity kém đi (contrast 0.274), vì
rollout sâu hơn làm dự đoán mượt/trung-bình-hoá → landscape phẳng quanh cua; nên chúng tôi giữ auto_steps 2.

---

## 5. TẦNG 2 — Planner OPEN-LOOP chọn JOINT (lái + ga) khớp người lái (✅)

Tầng 1 chỉ đo dự-đoán-latent; tầng 2 đo **quyết-định-của-planner** mà chưa chịu vật-lý-đóng-vòng. Quan
trọng, ở tầng này planner phải chọn **cả lái lẫn ga cùng lúc** chứ không chỉ lái. Trên session VAL held-out,
với mỗi frame thật chúng tôi đặt goal là patch map ~0.9s phía trước cùng session, rồi cho planner quét một
**lưới JOINT hai chiều (15 điểm lái × 9 điểm ga = 135 tổ hợp)** và lấy hành động model = argmin năng lượng
trên cả lưới — chọn lái và ga đồng thời, so với (lái, ga) người lái thật. Đây là open-loop trung thực vì
video luôn chạy theo người lái — model chỉ đề xuất, không được lái — nên nó **không** chứng minh "xe tự
lái". Kết quả trên ba session VAL tốt nhất (gộp 893 cửa sổ quẹo): góc lái model **khớp dấu người 94.2%**
(841/893), |Δsteer| trung vị ~0.07; và đáng chú ý là **model tự chọn ga hợp lý** —
91.9% số frame model muốn tiến (ga>0), với ga trung vị +0.075 rất sát mức người lái +0.090. Hai điều này
cho thấy planner đọc được **cả hai trục** hành động: khi tối ưu joint, lái vẫn đúng chiều ~94% và ga được
chọn độc lập ở mức hợp lý — không cần giữ ga = teacher. Diễn giải: năng lực lập kế hoạch là lành; cái gãy ở
Tầng 3 không phải vì "planner dốt".

---

## 6. TẦNG 3 — Phân tích thất bại Closed-loop (❌) — ba nguyên nhân

Khi triển khai teach & repeat ngoài trời (teach: lái tay chụp chuỗi ảnh-mốc + GPS dọc tuyến ~15m; repeat:
điện thoại stream frame+GPS+rotvec qua TCP về PC chạy V-JEPA → AC predictor → CEM rồi gửi 2-byte action về
ESP32), hệ thống bám tuyến tốt ở nửa đầu route rồi bung ra lề. Chỉnh tham số chỉ dời điểm bung chứ không
xoá, qua khoảng 10 run trong một môi trường mà không run nào về đích, nên kết quả là định tính + cơ chế. Phân
tích định lượng tách được ba nguyên nhân cộng hưởng.

**Nguyên nhân A — descriptor V-JEPA không bất-biến-sáng.** Khi tới một ảnh-mốc mà ảnh live (khác về heading,
ánh sáng, vị trí so với lúc dạy) không khớp ảnh dạy, độ tương đồng cosine giữa latent live và latent mốc tụt
xuống dưới 0.1 rồi âm, khiến goal không còn phân biệt được trong latent và năng lượng CEM phẳng theo lái. Đào
sâu bằng một probe thuần CPU trên latent (cặp session cross-lighting cách nhau ~53 giờ), chúng tôi đo thứ
hạng theo cosine của ảnh-dạy đúng-hình-học: khi sáng gần nhau, ảnh đúng ở hạng 0 (top-1 79%, descriptor
tốt); khi sáng xa nhau, ảnh đúng rơi xuống hạng trung vị 41–62 (top-1 chỉ 0–3%), tức tín hiệu per-frame sai
hẳn. Quan trọng là **khâu điều khiển không dính**: CEM chấm điểm bằng patch-L1 nên lighting-robust; vấn đề
chỉ ở khâu định-vị/pop dùng cosine trên latent pooled. Đây là một giới hạn của bản thân descriptor đóng băng,
chỉ sửa được tận gốc bằng cách học một descriptor bất-biến-sáng; cách kịp deadline là dạy lại cùng buổi.

**Nguyên nhân B — vùng-chết đứng-yên, không phải "OOD".** Ban đầu chúng tôi thấy năng lượng phẳng ở bãi và
kết luận model "OOD". Đo lại cho thấy điều này **sai**: ép speed=0 trên VAL làm contrast tụt từ 0.413 xuống
0.107 mà không hề đổi cảnh, và đo live tại chính park đó cho thấy khi ga≥0.07 thì contrast 0.2–0.57 còn khi
ga<0.06 mới phẳng. Cơ chế là `yaw = k_yaw·steer·speed`: khi xe đứng (speed=0) thì lái không sinh yaw, nên
predictor đúng khi cho "đứng thì cảnh không quay", và landscape phẳng. Gốc rễ là một deadlock: hộp ga CEM
chứa vùng chết, xe đứng → speed=0 → phẳng → ra rác → lại đứng. Khắc phục là đặt sàn ga TMIN=0.07, và xe lái
khoẻ trở lại.

**Nguyên nhân C — thiếu dữ liệu lateral-recovery.** Vì khi dạy xe luôn ở giữa tuyến, không ảnh dạy nào dạy
"lệch 2m thì bẻ về hướng nào"; một khi đã văng ra, thị giác chỉ báo cos thấp chứ không chỉ đường về. Chúng
tôi đã thử một khắc phục mức latent ("DAVE-2 cho V-JEPA", không cần GPU): dịch ngang lưới patch token để giả
lập camera lệch ngang rồi ghép nhãn bẻ-về, trộn vào BC của policy; đo offline cho thấy đáp ứng tự-sửa được
khuếch đại 3.4–5.4 lần và không hại goal-reaching. Tuy nhiên đây là proxy không có renderer nên không chứng
minh được transfer closed-loop offline, vì vậy mặc định tắt và chỉ bật sau khi probe trên xe.

So với Meta (tay máy, cảnh bàn cố định, không heading/ánh-sáng/lệch-ngang, "chính xác cm" thực ra là
proprioception sub-mm — khác hệ đo) và ViNG (chạy được vì policy train trên data có recovery), hệ của chúng
tôi khó hơn về robustness và thiếu đúng tín hiệu recovery. Tóm lại, gap giữa "dự đoán latent tốt + lập kế
hoạch khớp chuyên gia offline" và "lái được closed-loop ngoài trời" nằm ở độ-bền-định-vị, chế-độ-điều-khiển
và dữ liệu recovery, **không** ở chất lượng representation.

---

## 7. Đánh giá dữ liệu IMU

State token dùng 10 kênh IMU (gyro, accel, rotation-vector) cộng tốc độ GPS. Trên thực tế, chất lượng các
kênh này không đều. Vì điện thoại gắn trên xe, accel và gyro lẫn rung động khung, xóc mặt đường và rung
mount; thành phần az luôn lệch hằng số do trọng lực; ax/ay nhỏ và chìm trong nhiễu khi xe chạy. Tốc độ GPS
chỉ 1Hz trong khi frame ~8.5Hz nên phải nội suy, vừa trễ vừa mượt-hoá. Rotation-vector từ sensor-fusion của
điện thoại tương đối ổn cho pitch/roll (thái độ xe trên dốc/xóc) nhưng yaw≈heading bị drift và hiệu chỉnh la
bàn kém ngoài trời (chúng tôi đã thấy lệch ±50–180° khi thử geosteer). Hệ quả là trong 12 chiều state, chỉ
`speed` và `gz` (yaw-rate) là thật sự đáng tin cho điều khiển; phần accel/rotvec mang ít tín hiệu sạch, chủ
yếu để model "ngửi" được đang xóc hay đang nghiêng. Đánh giá này củng cố lựa chọn không cho predictor dự
đoán full state (§3.4) và là động lực cho hướng tương lai thay IMU điện thoại bằng cảm biến chuyên dụng.

---

## 8. Đính chính & Bài học phương pháp

Báo cáo minh bạch liệt kê những kết luận trung gian từng đưa ra rồi tự bác bằng đo lường. (1) "~26M tham số"
là sai — đếm trực tiếp từ checkpoint cho 39.2M. (2) "Model OOD ở park" là sai — landscape phẳng là do chế-độ
đứng-yên (ép speed=0 offline tụt contrast 0.41→0.11 mà không đổi cảnh), không phải scene-OOD. (3) "R²(speed)
= −1.1, encoder mù vận tốc hoàn toàn" là sai và không tái lập được — đo lại cho R²≈+0.30 held-out, tức latent
có tín hiệu tốc độ nhưng yếu. (4) "geosteer bằng rotvec sửa được trôi ngang" chưa kiểm dấu thật — chạy bãi
thì diverge vì rotvec yaw drift. Bài học xuyên suốt: đếm và đo trực tiếp thay vì chép số cũ; luôn so cùng hệ
đo (xe-chạy với xe-chạy); và tách confound thay vì gộp mọi hiện tượng vào một nhãn.

---

## 9. Thảo luận & Hạn chế

Đóng góp chính của báo cáo là một đánh giá đầu tiên của họ V-JEPA 2 trên một robot di động, với pipeline
offline rigorous (mọi số tái lập được bằng script), một kiểm chứng planner open-loop tách bạch "năng lực lập
kế hoạch" khỏi "robustness đóng vòng", và một phân tích thất bại closed-loop có cơ chế kèm đính chính minh
bạch. Hạn chế cần nêu rõ: closed-loop chỉ trong một môi trường, không run nào về đích, nên là kết quả định
tính; dữ liệu thiếu recovery; descriptor nhạy ánh sáng; GPS 1Hz nhiễu; IMU điện thoại nhiễu nên state chỉ
tin được speed và yaw-rate; encoder cần GPU nên phải qua PC với trễ CEM cao; và margin offline khiêm tốn,
trung thực là mức report/workshop chứ không phải SOTA.

---

## 10. Hướng phát triển

Hướng ưu tiên là **thay IMU điện thoại bằng cảm biến BNO055** (IMU 9-trục có sensor-fusion phần cứng) để có
orientation và gyro ổn định hơn nhiều, làm sạch state token. Tiếp theo là thu hoặc augment dữ liệu lateral-
recovery để fix nguyên nhân C, và học một descriptor bất-biến-sáng (head nhỏ trên frozen V-JEPA, train cross-
session — dữ liệu hiện có đã chứa cặp cùng-chỗ-khác-buổi) để fix nguyên nhân A. Xa hơn, một sim 3DGS dựng lại
bãi từ data sẽ cho phép test closed-loop trong nhà với heading/ánh-sáng kiểm soát được, và RTK GPS sẽ cho
định vị cm. Về đồ-thị-ảnh topological: chúng tôi đã thử nhanh dựng một đồ-thị ảnh-mốc để định vị toàn tuyến
và offline nó định vị được ~2m, nhưng **không dùng làm hệ chính** vì khó kiểm soát khi chạy thật (đường nối
các mốc zigzag, ảnh trong data khác ảnh đang chạy, các mốc ở xa nhau, vị trí mốc lấy từ GPS nên không chính
xác → rất khó debug); vì vậy hệ chính chốt ở teach & repeat tuyến tính. Một số nhánh khác (world model
pixel-JEPA end-to-end) là thử nghiệm, có thể quay lại như baseline trong tương lai.

---

## 11. Kết luận

Frozen V-JEPA 2.1 cung cấp một biểu diễn latent đủ tốt để một AC predictor ~39M tham số vượt baseline
identity ổn định ở mọi horizon, nhạy với cả lái lẫn ga, hưởng lợi từ transfer chéo-domain-servo, và để
planner chọn joint cả lái lẫn ga khớp người lái (lái đúng chiều ~94%, ga tự chọn muốn-tiến ~92%) trên video
held-out theo lối open-loop. Tuy nhiên, triển khai
closed-loop ngoài trời bung ra lề do ba nguyên nhân cộng hưởng — descriptor không bất-biến-sáng, chế-độ đứng-
yên làm phẳng landscape (đã đính chính nhãn "OOD" sai), và thiếu dữ liệu lateral-recovery. Đây là đánh giá
đầu tiên của họ V-JEPA 2 trên một robot di động và một negative finding trung thực, có cơ chế và đã đính
chính các kết luận trung gian sai: với cùng một biểu diễn mạnh, khoảng cách tới "lái được closed-loop ngoài
trời" nằm ở độ-bền-định-vị, chế-độ-điều-khiển và dữ liệu recovery, không ở chất lượng representation.
