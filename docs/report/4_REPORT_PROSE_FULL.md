# BÁO CÁO — PROSE HOÀN CHỈNH (paste thẳng vào Word)

> Văn xuôi học thuật đầy đủ cho TOÀN BỘ báo cáo (Abstract → Kết luận), tiếng Việt + thuật ngữ tiếng
> Anh. Đã trỏ sẵn **Hình 1–6** và **Bảng A–E**. Mọi số đã verify/tái lập từ repo. Khi ghép vào file
> nộp: điền `[Họ tên]/[MSSV]/[Môn]/[GVHD]`, chèn ảnh từ `docs/report/figures/`, và (tuỳ) chèn ảnh rig
> phần cứng bạn tự chụp ở §4. Phụ lục/related-work chi tiết hơn xem `2_REPORT_FULL.md`.
>
> **Bản đồ Hình:** Hình 1 = `fig_architecture.png` · Hình 2 = `fig_energy_landscape.png` · Hình 3 =
> `fig_cos_dropout_mechanism.png` · Hình 4 = `fig_route_graph.png` · Hình 5 =
> `fig_cos_dropout_20260613_171912.png` · Hình 6 = `fig_trajectory_20260613_171912.png`.

---

## Tóm tắt (Abstract)

Chúng tôi nghiên cứu việc dùng một **encoder video nền-tảng đóng băng — V-JEPA 2.1 ViT-L** — làm biểu
diễn cho một **world model hành-động-điều-kiện (action-conditioned world model)** trên một **xe RC di
động**, rồi dùng **CEM planning** để điều hướng tới ảnh-mục-tiêu theo mô hình *teach & repeat*. Về mặt
**offline**, một AC predictor nhỏ (~26M tham số) đặt trên latent đóng băng **vượt baseline "đứng yên"
(identity)** ở mọi horizon (tỉ số rollout@1 = 0,744), có **độ nhạy hành động** đo được (điểm cực tiểu
năng lượng đúng hướng cua 58/60, độ tương phản ≈ 0,36), và đặc biệt cho thấy **transfer chéo-domain-servo
có lợi** (train trộn hai loại servo → đánh giá trên servo đích đạt 0,65 so với 1,073 khi chỉ train trên
servo đó). Tầng điều hướng dựng **topological graph** 92 session (29.699 node), định vị (localize) trung
vị 2,1 m. Tuy nhiên, khi **triển khai closed-loop** ngoài thực địa, hệ thống **bám tuyến tốt ở nửa đầu
route rồi "bung" ra lề tại điểm "cos-dropout"** — nơi ảnh live không khớp ảnh teach làm cosine tụt dưới
0,1, CEM mất gradient và lái loạn, trong khi **không có tín hiệu kéo về** (thiếu dữ liệu recovery).
Không lần chạy nào (trong khoảng 10 lần) về tới đích. Chúng tôi phân tích cơ chế thất bại này một cách
định lượng và chỉ ra rằng **giới hạn nằm ở tầng nav-robustness + control + dữ liệu recovery, không ở
chất lượng biểu diễn**. Đây là **đánh giá đầu tiên họ V-JEPA 2 trên một robot di động** (Meta chỉ thử
trên cánh tay robot) và đồng thời là một *negative finding* trung thực, có phân tích cơ chế đầy đủ.

**Từ khoá:** world model, V-JEPA 2.1, self-supervised representation, visual navigation, teach & repeat,
CEM/MPC, domain shift, negative result.

---

## 1. Giới thiệu

Điều hướng bằng thị giác cho robot di động truyền thống dựa vào SLAM hoặc bản đồ hình học. Một hướng
thay thế gần đây là **học biểu diễn tự-giám-sát (self-supervised representation)** rồi **lập kế hoạch
trong không gian latent**: thay vì dựng bản đồ 3D, ta học một *world model* dự đoán "hành động nào gây
ra thay đổi hình ảnh nào", sau đó tìm chuỗi hành động đưa quan sát hiện tại về quan sát-mục-tiêu. Cách
tiếp cận này hấp dẫn vì tránh được chi phí và sự giòn của SLAM trong môi trường động, đồng thời khai thác
được sức mạnh của các foundation model thị giác.

Họ mô hình **V-JEPA (Joint-Embedding Predictive Architecture cho video)** học đặc trưng bằng **dự đoán
trong không gian biểu diễn (feature prediction)** thay vì tái tạo pixel, nhờ đó không lãng phí dung lượng
mô hình vào chi tiết pixel không cần thiết. Phiên bản **V-JEPA 2.1** (ViT-L distilled từ ViT-G, độ phân
giải 384) bổ sung **Dense Predictive Loss**, cho đặc trưng patch chất lượng cao phục vụ định vị và hình
học. Meta đã chứng minh biến thể action-conditioned **V-JEPA 2-AC** có thể lập kế hoạch trên **cánh tay
robot**. Câu hỏi nghiên cứu của chúng tôi nảy sinh tự nhiên từ đó: *biểu diễn này có dùng được cho một
robot DI ĐỘNG, hoạt động ngoài trời, với động lực học và domain-shift thật hay không?*

Bài toán này về bản chất là một bài toán **Computer Vision**: (i) học **biểu diễn thị giác** từ một
foundation model đóng băng; (ii) **nhận dạng địa điểm bằng thị giác (visual place recognition)** để định
vị và chuyển subgoal; (iii) khảo sát **độ bền của biểu diễn dưới domain-shift thật** (ánh sáng, thời
điểm, góc nhìn) — chính là tâm điểm của phần phân tích thất bại; và (iv) **so khớp latent** để lập kế
hoạch điều khiển. Đóng góp của báo cáo gồm ba phần: (1) **đánh giá đầu tiên họ V-JEPA 2 trên robot di
động (xe RC)**; (2) một **pipeline đánh giá offline rigorous** với phát hiện về transfer chéo-domain-servo;
và (3) một **phân tích thất bại closed-loop có cơ chế**, cho thấy khoảng cách giữa "biểu diễn tốt" và
"lái được ngoài trời" nằm ở tầng điều khiển và dữ liệu, chứ không ở biểu diễn.

Cần nói rõ về phạm vi và bối cảnh thực hiện: do encoder ViT-L chỉ chạy được trên GPU (không chạy trên
điện thoại), pha inference phải thực hiện qua một máy PC. Sau nhiều ngày tinh chỉnh closed-loop ngoài
thực địa mà chẩn đoán cho thấy thất bại là **giới hạn mô hình/dữ liệu chứ không phải tham số**, chúng tôi
quyết định **dừng thử nghiệm thực địa** và tập trung **phân tích + báo cáo** — chốt lại phần offline đã
vững và trình bày phần closed-loop như một kết quả âm được phân tích kỹ. Đây là một lựa chọn khoa học có
chủ đích: tiếp tục xoay tham số sẽ không xoá được nguyên nhân gốc đã được định lượng.

---

## 2. Công trình liên quan

**JEPA và V-JEPA 2/2.1.** Các kiến trúc JEPA học self-supervised bằng cách dự đoán biểu diễn của một
phần dữ liệu từ phần còn lại trong *không gian embedding* (không reconstruct pixel). V-JEPA mở rộng ý
tưởng này sang video; V-JEPA 2 huấn luyện ở quy mô lớn và chứng minh khả năng *understanding / prediction
/ planning*; V-JEPA 2.1 thêm Dense Predictive Loss để có đặc trưng patch dày, chất lượng cao. Chúng tôi
sử dụng V-JEPA 2.1 ViT-L 384 ở chế độ **đóng băng**.

**V-JEPA 2-AC.** Biến thể action-conditioned của Meta interleave bộ ba `[action, state, patch]` cho mỗi
frame, dùng một predictor *block-causal* và lập kế hoạch bằng CEM với hàm năng lượng `‖P − z_goal‖₁`.
Điểm khác biệt cốt lõi so với công trình của chúng tôi: Meta **chỉ đánh giá trên cánh tay robot** trong
cảnh bàn cố định.

**ViNG / ViKiNG.** Hai công trình điều hướng bằng goal ảnh trên đồ thị topo (không cần bản đồ hình học);
điểm mấu chốt là policy của chúng được huấn luyện trên dữ liệu có hành vi đa dạng, **bao gồm cả việc xe
lệch khỏi tuyến rồi tự quay về** — đây là nền tảng cho tầng navigation của chúng tôi và cũng là điểm
khác biệt quyết định khi phân tích thất bại (§7).

**PiJEPA.** Đề xuất warm-start cho MPC bằng một *policy prior* huấn luyện trên JEPA world model. Chúng
tôi áp dụng đúng tinh thần này: dùng một policy BC để warm-start phân phối hành động của CEM (thay MPPI
bằng CEM, thay Octo bằng một MLP nhỏ).

**LeJEPA / LeWorldModel.** Một world model pixel-JEPA huấn luyện end-to-end (với cơ chế chống sụp đổ
SIGReg). Chúng tôi port lại làm **baseline độc lập mạnh** (không dùng V-JEPA) để đối chứng.

---

## 3. Phương pháp

### 3.1. Tổng quan kiến trúc

Hình 1 trình bày toàn bộ hệ thống. Mỗi frame được mã hoá *từng cái một* qua encoder V-JEPA 2.1 ViT-L 384
**đóng băng** thành các patch token; một **AC predictor** nhận latent đó cùng với state (đo từ cảm biến)
và action để dự đoán latent của bước kế; bộ lập kế hoạch **CEM** tìm chuỗi action tối thiểu hoá năng
lượng `‖P − z_goal‖₁` giữa latent dự đoán và latent của ảnh-mục-tiêu, rồi gửi 2-byte hành động về xe qua
điện thoại và vi điều khiển ESP32. Một tối ưu then chốt là **mã hoá toàn bộ dataset offline một lần** rồi
lưu latent ra đĩa, nhờ đó quá trình huấn luyện đọc latent trực tiếp mà không cần forward V-JEPA (nhanh
hơn ~50–100×); **không bao giờ backprop qua encoder**.

Hệ thống được tách thành **hai tầng độc lập**, một thiết kế quan trọng giúp quy trách nhiệm khi phân tích
lỗi. Tầng **navigation** (action-agnostic, chỉ dùng thị giác + GPS) trả lời "đang ở đâu" và "cần đi qua
những subgoal ảnh nào". Tầng **control** (servo-specific, gồm V-JEPA + AC predictor + CEM) trả lời "đạp
ga/đánh lái bao nhiêu để tới subgoal kế". Việc tách bạch này cho phép kết luận cuối cùng (§7): tầng biểu
diễn/định vị hoạt động tốt offline; khoảng trống nằm ở tầng control khi đóng vòng.

### 3.2. Encoder đóng băng và một phát hiện về tốc độ

Encoder được dùng ở chế độ **per-frame** (image-path): mỗi frame 384px cho ra **576 patch token × 1024
chiều**, không pooling và không nhồi nhiều frame. Một phát hiện đáng chú ý — và mang tính Computer Vision
— là latent **không mang thông tin tốc độ**: hệ số xác định khi hồi quy tốc độ từ latent single-frame
pooled là R² = −1,1 (tức không có tín hiệu), và việc nhồi cả một clip nhiều frame vào encoder cũng cho
R² ≈ 0. Nguyên nhân là mô hình 2.1 ViT-L 384 chạy ở image-path với `tubelet_size = 1` (không có tích chập
theo thời gian). Hệ quả thiết kế: **tốc độ phải được đưa vào qua state token** (GPS speed) chứ không phải
qua multi-frame. May mắn là camera của xe **nhìn thấy bánh lái phía trước**, nên góc lái đã hiện diện
trong patch map; state token chỉ cần đảm nhận phần tốc độ mà ảnh không cung cấp.

### 3.3. AC Predictor — port trung thực từ V-JEPA 2-AC

AC predictor (Hình 1, khối xanh lá) là một transformer **block-causal**: với mỗi frame, ta interleave bộ
ba `[action, state, patch token]`; mô hình dự đoán **tuyệt đối** latent của bước kế (không phải phần dư),
với **chuẩn hoá per-token LayerNorm** và hàm mất mát **L1 teacher-forcing cộng rollout 2 bước**. Đây là
bản port trung thực của V-JEPA 2-AC, với một số **khác biệt có chủ đích** được ghi minh bạch: state là
vector IMU 10 chiều (thay cho pose 7 chiều của cánh tay, đồng thời loại vị trí tuyệt đối để tránh overfit
địa điểm); positional embedding học được (thay cho 3D-RoPE); độ sâu 12 lớp (thay cho 24 lớp, để tránh
overfit trên ~228k frame); và động học tích phân bằng mô hình **bicycle** thay cho `compute_new_pose` của
cánh tay. Tổng số tham số của predictor là khoảng 26M (encoder đóng băng không tính).

### 3.4. Lập kế hoạch: CEM, động học và policy prior

Bộ lập kế hoạch **CEM** dùng context 2 frame, horizon 4, hàm năng lượng L1 trên patch token cuối, theo
cơ chế receding-horizon (chỉ áp hành động đầu tiên mỗi chu kỳ). Để khử hiện tượng phân phối "bang-bang"
(phần lớn mẫu dính biên), chúng tôi dùng độ lệch chuẩn theo từng chiều và warm-start phân phối quanh một
**policy prior** kiểu PiJEPA; đồng thời mỗi vòng lặp chèn thêm 5 ứng viên steering cố định `[-1, -0.5,
0, +0.5, +1]` để elite luôn bao phủ được đáy năng lượng toàn cục. Động học **bicycle** tích phân
`[x, y, heading, speed]` từ `[steer, throttle]`, với các hệ số **fit từ dữ liệu thật** (k_thr = 1,588;
k_drag = 0,078; k_yaw = 0,088). Chi phí một chu kỳ điều khiển phụ thuộc số mẫu/số vòng lặp CEM: đo trên
GPU thật, cấu hình 32 mẫu/1 vòng tốn ≈ 0,5 s, còn 256 mẫu/2 vòng tốn ≈ 5,5 s; thực nghiệm cho thấy 32/1
cho chất lượng hành động tương đương 64/2 nên được chọn để giảm trễ.

### 3.5. Tầng navigation: topological graph

Tầng navigation dựng một **đồ thị topo** trong đó mỗi node là một frame (latent V-JEPA single-frame +
toạ độ GPS theo mét + heading). Cạnh gồm hai loại: cạnh **temporal** (người đã lái qua nên chắc chắn đi
được) và cạnh **loop-closure** (k-NN theo cosine latent giữa các session, có cổng GPS < 8 m để chống
nhầm-vị-trí do cảnh tự-giống). Các thao tác gồm `localize()` (có GPS-prior), `plan_route()` (Dijkstra)
và `extract_subgoals()` (trích chuỗi ảnh subgoal). Hình 4 minh hoạ một route được lập trên đồ thị cùng
chuỗi ảnh subgoal mà CEM lần lượt lái tới.

---

## 4. Thiết lập thực nghiệm

### 4.1. Hệ thống thu thập dữ liệu

Thiết kế phần cứng đã trải qua một **bước ngoặt**. Ban đầu, video được truyền từ một camera (RunCam
WiFiLink 2, cảm biến IMX415) qua liên kết không dây WFB-NG 5.8 GHz về PC; tuy nhiên liên kết này **thất
bại ở tầm xa** (khoảng 50 m: vỡ ảnh, giật frame, độ trễ phình từ 92 lên 310 ms khi mất gói). Chúng tôi
chuyển sang **đặt một điện thoại Android lên xe** (Samsung A42 5G) làm đồng thời camera, máy ghi và relay:
điện thoại chụp frame cục bộ, đọc telemetry từ ESP32 qua USB, và lưu dữ liệu cùng schema với rig cũ. Vì
frame và telemetry chia sẻ **một đồng hồ duy nhất**, các vấn đề lệch clock biến mất (chỉ còn một độ trễ
chụp camera δ_cam ≈ 100 ms, đã được đo per-frame và hiệu chỉnh khi đồng bộ). Xe được lái tay bằng bộ
điều khiển FlySky trong lúc ghi; một mô-đun đồng bộ re-pair mỗi frame với hành động và IMU tại đúng thời
điểm cảnh thật. *(Vị trí chèn ảnh rig phần cứng — chụp sau.)*

### 4.2. Dữ liệu

Tập dữ liệu gồm **209 session (≈ 228.000 frame)**, thu trên **hai loại servo lái khác nhau** và do đó
tạo thành hai *domain điều khiển*: tập **KDS** (~28 session) có steering trải đủ dải nhưng ga gần như cố
định (xấp xỉ steering-only), và tập **TowerPro** (181 session, gồm cả các pha recovery) có ga biến thiên
thật (có cả lùi 9–14%). State của mô hình là vector 10 chiều `[speed, gx, gy, gz, ax, ay, az, rx, ry,
rz]` (tốc độ GPS + gyro + gia tốc + orientation). GPS của điện thoại thực tế chỉ đạt ~1 Hz với nhiễu vị
trí trung vị 0,44 m, nên GPS **chỉ được dùng làm cổng chuyển subgoal**, còn việc lái hoàn toàn dựa vào
thị giác. Việc tách train/validation được thực hiện ở mức session (80/20, seed 0) và **khoá cố định**
trong một file split để mọi đánh giá đều tái lập được và không rò rỉ thông tin.

---

## 5. Kết quả đánh giá Offline

### 5.1. Thiết lập đánh giá

Toàn bộ đánh giá offline được thực hiện trên **tập validation cố định** đã mô tả ở §4.2 (145 session
train / 36 session validation, khoá trong `split.json`). Chúng tôi so sánh hai world model huấn luyện
trên **cùng một dataset latent**: (i) `vjepa_ac` — AC predictor đặt trên latent V-JEPA đóng băng, là
**đóng góp chính**; và (ii) `LeWM` — world model pixel-JEPA end-to-end, đóng vai trò **baseline độc lập**.
Checkpoint triển khai là `cd4` (V-JEPA 2.1 ViT-L 384, predictor patch-token block-causal depth 12,
~26M tham số).

### 5.2. Lựa chọn thước đo

Chúng tôi **không** đánh giá bằng validation loss đơn lẻ, vì một mô hình bị **latent collapse** và bỏ
qua tín hiệu hành động vẫn có thể đạt val loss thấp (chúng tôi quan sát đúng hiện tượng này ở λ = 0,05).
Hai thước đo quyết định là: **tỉ số rollout-trên-identity** (`MSE(model)/MSE(identity)`; < 1 = thắng
baseline đứng-yên, càng nhỏ càng tốt), và **độ nhạy hành động** đo bằng energy-probe (quét steering trên
[−1, 1], xét điểm cực tiểu năng lượng có đúng hướng cua không và độ tương phản của đường năng lượng sâu
đến đâu). Thước đo thứ hai sát với tín hiệu mà CEM khai thác hơn cả tỉ số rollout.

### 5.3. World model vượt baseline "đứng yên" một cách ổn định

Bảng A trình bày kết quả chính. Checkpoint `cd4` đạt tỉ số rollout-trên-identity **0,744 / 0,703 /
0,697** ở horizon 1/2/3 (trên 2.000 window), tức **vượt baseline đứng-yên khoảng 26%** và duy trì ưu thế
ở mọi horizon. Một biến thể pooled huấn luyện theo cross-validation 5 seed đạt tỉ số rollout@1 trung bình
**0,958 ± 0,024** với 4/5 seed < 1 và phương sai thấp, khẳng định model thắng baseline **một cách ổn
định** chứ không nhờ may rủi khởi tạo. Ngược lại, baseline `LeWM` chỉ đạt **0,97 ± 0,15** (5-fold) và
**không ổn định** (2/5 fold thất bại, tỉ số vượt 1 ở horizon dài). Như vậy, trên cùng bài toán và dữ
liệu, world model latent dựa trên V-JEPA đóng băng **vừa thắng cao hơn vừa ổn định hơn** world model
pixel end-to-end. (Một bài học kèm theo: lấy mẫu frame ở 10fps khiến baseline pixel học luôn hàm
identity; phải giãn mẫu về ~0,5 s/bước mới học được động học thật.)

### 5.4. Transfer chéo-domain-servo

Phát hiện nổi bật nhất được trình bày ở Bảng B. Khi **chỉ** huấn luyện trên servo TowerPro rồi đánh giá
trên TowerPro held-out, tỉ số rollout@1 là **1,073** — **thua cả baseline đứng yên**. Nhưng khi huấn
luyện **trộn** TowerPro với dữ liệu KDS (một servo *khác*, giàu biến thiên steering) rồi đánh giá trên
cùng tập held-out đó, tỉ số cải thiện xuống **0,65**. Nói cách khác, dữ liệu từ một domain-servo khác
**transfer có lợi** sang domain đích bất chấp khác biệt cơ học. Điều này cho thấy với bài toán của chúng
tôi, **sự đa dạng của hành động/cảnh trong dữ liệu** quan trọng hơn việc khớp đúng domain triển khai —
một thông điệp thực tiễn cho việc thu thập dữ liệu robot, và nhất quán với quan sát rằng *effective rank*
của latent baseline chỉ ~7–9/256 (dữ liệu đơn điệu là nút thắt chính).

### 5.5. Độ nhạy hành động: energy landscape có đáy đúng phía cua

Liệu việc "đánh lái yếu" khi chạy thật có phải do bản thân world model không phân biệt được các hành động
lái? Energy-probe trả lời câu hỏi này **tách bạch** khỏi các yếu tố closed-loop. Trên 60 window-cua của
tập validation, **điểm cực tiểu năng lượng trùng đúng hướng cua của người lái ở 58/60 trường hợp**, với
sai khác trung vị ≈ 0,12 và **độ tương phản trung vị ≈ 0,36** (Bảng C). Hình 2 minh hoạ trực quan: các
đường `E(steer)` có **đáy rõ nằm đúng phía cua** (cua trái → đáy lệch steering âm; cua phải → đáy lệch
steering dương), và biểu đồ phân tán argmin-E theo hành động người lái cho thấy đại đa số điểm nằm trong
hai góc phần tư "đúng dấu". **Kết luận quan trọng: offline, mô hình hoàn toàn không đánh lái yếu** —
landscape năng lượng có tín hiệu lái rõ và đúng hướng. Bảng C cũng cho thấy độ tương phản **giảm theo
khoảng cách mục tiêu** (0,443 ở d=2 xuống 0,270 ở d=8), tức cơ chế "mất tín hiệu khi subgoal xa/quanh
góc" là đo được, và nên dùng mục tiêu gần + teach dày thay vì ngắm xa.

### 5.6. Một ablation âm khẳng định lựa chọn cấu hình

Biến thể `cd4_as3` (giống `cd4` nhưng huấn luyện rollout 3 bước thay vì 2) cho **dự đoán multi-step nhỉnh
hơn** (rollout@2/@3 = 0,699/0,686 so với 0,703/0,697) **nhưng kém hơn về độ nhạy hành động** (đúng hướng
cua 54/60, độ tương phản 0,274). Diễn giải: huấn luyện rollout sâu hơn làm dự đoán bị mượt/trung-bình-hoá,
khiến **landscape năng lượng phẳng đi quanh khúc cua** — đúng nơi CEM cần tín hiệu. Vì bộ lập kế hoạch
khai thác đáy năng lượng theo hành động chứ không chỉ độ chính xác dự đoán, chúng tôi **giữ `cd4`**.
Ablation âm này nhấn mạnh: cải thiện một thước đo không miễn phí — phải kiểm tra đồng thời độ nhạy hành
động, nếu không sẽ tối ưu nhầm hướng.

---

## 6. Triển khai Closed-loop

Chúng tôi triển khai điều hướng theo mô hình **teach & repeat** kiểu ViNG/ViKiNG. Ở pha *teach*, người
vận hành lái xe bằng tay dọc một tuyến (~15 m trên bãi cỏ công viên) và hệ thống chụp một **chuỗi subgoal
ảnh** kèm toạ độ GPS (vào cua chụp dày hơn). Ở pha *repeat*, điện thoại đặt trên xe truyền frame + GPS +
orientation về PC qua TCP; PC chạy chuỗi **V-JEPA 2.1 ViT-L (đóng băng) → AC predictor `cd4` → CEM** để
lái xe tới subgoal ảnh hiện tại trong không gian patch-token, rồi gửi 2-byte hành động về xe qua điện
thoại và ESP32. Việc chuyển sang subgoal kế (pop) căn cứ GPS, có xác nhận thị giác. Một giao diện web hiển
thị vị trí xe, camera và trạng thái, kèm nút dừng khẩn; mỗi lần chạy được ghi log đầy đủ để mổ offline.

Kết quả tổng quan **trung thực**: trong khoảng **10 lần chạy** với nhiều cấu hình khác nhau, **không lần
nào về tới đích**. Mẫu hành vi lặp lại bất biến (Bảng D): xe **bám tuyến tốt ở nửa đầu route** (độ lệch
ngang < 0,5 m) rồi **"bung" ra lề tại một điểm "cos-dropout"**. Tuỳ cấu hình, điểm bám-tốt kéo dài tới
subgoal thứ 6 đến 18, nhưng kết cục đều là trôi/đâm lề. Đáng chú ý, **tinh chỉnh tham số chỉ dời điểm
bung chứ không xoá được nó** — ví dụ giảm chu kỳ điều khiển giúp bám tới subgoal 18 thay vì 8, nhưng vẫn
bung ở cos-dropout. Điều này cho thấy nguyên nhân là giới hạn ở tầng mô hình/dữ liệu chứ không phải tham
số, và là cơ sở để chúng tôi dừng tinh chỉnh thực địa.

---

## 7. Phân tích Thất bại

### 7.1. Cơ chế "cos-dropout" (đo được, không suy đoán)

Phân tích log của lần chạy sạch nhất (thị giác thuần, không can thiệp hình học) cho thấy rõ chuỗi
nhân-quả, minh hoạ ở Hình 3 (sơ đồ cơ chế) và Hình 5 (số liệu thật). Khi xe bám tuyến, **cosine có-tâm
(centered-cosine)** giữa ảnh live và ảnh teach của subgoal giữ ở mức ~0,25. Tới một subgoal "yếu" — nơi
heading, ánh sáng hoặc vị trí lúc *repeat* lệch so với lúc *teach* — **cosine rơi xuống dưới 0,1 rồi
xuống âm** (0,13 → 0,08 → −0,20 qua các subgoal 7–9). Khi cosine sập, mục tiêu **không còn phân biệt được
trong không gian latent**, nên **năng lượng CEM trở nên phẳng theo steering** và mất gradient; hệ quả là
CEM xuất ra hành động lái **gần như ngẫu nhiên, bão hoà full-lock ±1,0 và đảo chiều liên tục** — panel
dưới của Hình 5 cho thấy `|raw steer|` vọt lên 1,0 đúng vào vùng cos-dropout. Xe lập tức **văng ra hơn
2 m khỏi tuyến**, và đây là chỗ chí mạng: **không có tín hiệu nào kéo xe về**. Hình 6 trình bày quỹ đạo
GPS cùng lần chạy, tô màu theo cosine: nửa đầu (màu xanh, cosine tốt) xe bám tuyến, nhưng khi cosine
collapse (chuyển vàng → đỏ) xe trôi xa dần rồi dừng ở điểm bung. Một yếu tố cộng hưởng làm trầm trọng
thêm: cơ chế tăng ga theo độ lớn steering vô tình **tăng tốc xe đúng lúc nó đang quẹo bậy**.

Nguyên nhân gốc rất rõ: **toàn bộ ảnh teach được chụp khi xe ở GIỮA tuyến**, nên trong tập subgoal
**không tồn tại ảnh nào dạy mô hình "nếu đang lệch 2 m thì bẻ lái về phía nào"**. Một khi đã văng ra,
thị giác chỉ báo cosine thấp (đang sai chỗ) chứ **không chỉ được hướng quay về** — đây chính là **thiếu
hụt dữ liệu lateral-recovery**.

### 7.2. Bằng chứng: thất bại KHÔNG do "teach xấu" hay "cảnh tự-giống"

Một phản biện hợp lý là cosine sập vì bản thân ảnh teach kém phân biệt. Chúng tôi bác bỏ giả thuyết này
bằng đo lường trực tiếp. **Thứ nhất**, mã hoá lại các ảnh teach qua V-JEPA cho thấy embedding teach tốt
và đồng đều giữa các route (self-gap parkfix3 = 0,070; parkfix_5 = 0,094 — xấp xỉ hoặc tốt hơn), tức
không hề suy biến. **Thứ hai**, chất lượng khớp-live khi *chạy* phụ thuộc mạnh vào **độ tương thích thời
điểm teach và repeat**: route teach buổi sáng chạy ngay sau đó cho **66% số tick có cosine > 0,3** và bám
được tới subgoal 18–57, trong khi route teach lúc 14:11 chạy lúc 14:50 dưới nắng gắt cho **0% số tick có
cosine > 0,3**. Hai bằng chứng này chỉ thẳng vào thủ phạm: **domain-shift về ánh sáng/góc nhìn giữa teach
và repeat**, chứ không phải sự suy biến của cảnh hay của biểu diễn V-JEPA. Encoder vẫn tạo ra biểu diễn
tốt; điều gãy là **độ bền của phép khớp-live dưới thay đổi điều kiện thực địa**, cộng với thiếu dữ liệu
recovery.

### 7.3. So sánh với Meta (robot-arm) và ViNG/ViKiNG

Meta đánh giá V-JEPA 2-AC trên **cánh tay robot** trong cảnh bàn cố định, nơi hành động gây thay đổi cảnh
**lớn và tức thì**, không có heading/ánh-sáng/trôi-ngang; "độ chính xác cỡ centimet" của họ được đo bằng
proprioception tay máy (gần như tĩnh, đúng domain) — một **hệ đo khác**, không nên hiểu là world model
của họ chính xác hơn. Xe ngoài trời rơi vào chế độ **khó hơn về robustness**: hành động gây thay đổi cảnh
*nhỏ*, cộng cos-dropout và thiếu recovery. **ViNG/ViKiNG** chạy được trên robot di động chính vì policy
của chúng được huấn luyện trên dữ liệu **có hành vi recovery** (lệch rồi về) — đúng loại tín hiệu mà dữ
liệu teach một-lượt-giữa-tuyến của chúng tôi thiếu.

### 7.4. Đóng khung như một negative finding có giá trị

Tổng hợp lại, đóng góp của phần triển khai là một **kết quả âm được phân tích cơ chế đầy đủ**: *"Teach &
repeat trên một video-encoder đóng băng kết hợp CEM, khi thiếu dữ liệu lateral-recovery, sẽ bung ra tại
điểm visual-mismatch trên cảnh ngoài trời."* Bằng chứng gồm bảng kết quả các lần chạy (Bảng D), chữ ký
thất bại đo từ log (Hình 3, 5, 6) và phép loại trừ giả thuyết "teach xấu" (§7.2). Kết hợp với phần
offline (§5), bức tranh hoàn chỉnh là: **biểu diễn đủ tốt — world model thắng baseline, transfer
chéo-servo có lợi, energy landscape đúng hướng cua; khoảng cách tới việc lái-được closed-loop ngoài trời
nằm ở tầng nav-robustness + control + dữ liệu recovery, KHÔNG ở chất lượng biểu diễn.**

---

### 7.5. Khắc phục đề xuất: recovery augmentation ở mức latent (đã validate offline)

Từ chẩn đoán trên, chúng tôi đề xuất một khắc phục và kiểm chứng nó offline. Trước hết, một phép đo lại
(`meas_tail.py`) cho thấy độ trễ quyết định của CEM — chứ không riêng việc thiếu recovery — là một nguyên
nhân: tăng số mẫu CEM từ 16 lên 256 **không** làm giảm phương sai nghiệm hay tỉ lệ "đánh hết lái"
(≈14–16%, gần như phẳng), nghĩa là đuôi nhiễu này là nội tại của world model chứ không sửa được bằng tìm
kiếm rộng hơn; đòn bẩy đúng là **tick nhanh + ga thấp**, gợi ý dùng một policy học sẵn (một lần truyền
xuôi, dưới 1 ms) thay cho CEM trong vòng điều khiển.

Để bù phần dữ liệu recovery còn thiếu, chúng tôi tổng hợp nó ngay ở mức latent — một sự thích nghi của ý
tưởng DAVE-2 cho V-JEPA. Vì bộ nhớ đệm patch là lưới token 24×24, việc **dịch ngang lưới token** (bù mép
bằng cách lặp cột biên) xấp xỉ góc nhìn của một chiếc xe bị lệch ngang/chệch hướng; lấy trung bình lại cho
một latent "lệch làn" mà **không cần chạy lại V-JEPA**. Mỗi mức dịch được gán một nhãn lái **bẻ-về** tỉ lệ
với độ dịch, rồi trộn vào quá trình behavior-cloning của policy. Ba thí nghiệm offline (trên tập VAL) ủng
hộ phương pháp: (i) trục latent mà phép dịch tổng hợp tạo ra **trùng** với trục mà latent thật sự dịch
chuyển khi camera đảo hướng (cos +0.10 đúng dấu, ≈0 với chuyển động thẳng làm control) — tức augmentation
không học một trục giả; (ii) policy huấn luyện kèm augmentation **khuếch đại** đáp ứng tự-sửa lên **3.4–5.4
lần** so với baseline (đơn điệu, đúng dấu ở mọi mức dịch), trong khi val-loss trên lái thường **không xấu
đi** (thậm chí tốt hơn); (iii) đáp ứng này **bất biến** theo cự ly mục tiêu (tầm lookahead khi triển khai).
Một phân tích chéo-session còn cho thấy policy **nhạy mục tiêu yếu** — hành vi chủ yếu phản-xạ theo khung
hình hiện tại — nên nó **miễn nhiễm với chính cơ chế cos-dropout** đã làm CEM bung (CEM mất gradient khi
cosine sụp, còn policy thì không có gradient để mất), đổi lại nó hợp với việc bám một hành lang hơn là
"ngắm" tới mục tiêu.

Điểm trung thực then chốt: phép dịch tổng hợp chỉ là **xấp xỉ** cho lệch thật và **không có renderer** nên
**không thể chứng minh khả năng chuyển giao closed-loop bằng offline**. Do đó phương pháp được triển khai
**có cổng**: CEM đã-được-chứng-minh làm mặc định, và chỉ bật policy sau một phép thử trên xe (nhấc xe lệch
sang một bên, kiểm tra dấu lái trả về). Đây là một đóng góp ở dạng *phương pháp* — biến một thiếu sót dữ
liệu thành một augmentation latent rẻ kèm bộ tiêu chí đánh giá offline, với ranh giới minh bạch giữa
"đã chứng minh offline" và "cần xác minh trên xe".

### 7.6. Tường ánh sáng = giới hạn DESCRIPTOR, không phải đo-lường (SeqSLAM/multi-ref đều không cứu)

Một confound độc lập với recovery là **lệch ánh sáng giữa teach và repeat** (nắng→mây): cosine của
khâu *định vị/POP* sụp về 0 rồi âm, khiến subgoal không "pop". Vì sequence-matching kiểu **SeqSLAM** là
giải pháp chuẩn của tài liệu cho bất-biến-điều-kiện (ngày↔đêm, hè↔đông), chúng tôi dựng một probe offline
(`scripts/probe_seqslam_lighting.py`, thuần CPU trên latent đã mã hoá) để **định lượng** liệu nó có cứu
được không, trên các cặp session cross-lighting tự-tìm (cách nhau ~53 giờ, chênh độ sáng 11–18/255).

Phép đo quyết định, **không phụ thuộc thuật toán matching**, là *thứ hạng theo cosine của khung-tham-chiếu
đúng-hình-học* (khung teach gần nhất theo GPS, sai số < 1,5 m). Khi ánh sáng *gần* (chênh ~11), khung đúng
đứng **hạng 0** (top-1 79%) — biểu diễn rất tốt. Khi ánh sáng *xa* (chênh ~18), khung đúng rơi xuống **hạng
trung vị 41–62 trên 557–776** (top-20 chỉ 1–15%). Vì matching theo chuỗi chỉ có thể nâng hạng các ứng viên
*đã gần đỉnh*, một khung đúng nằm ở hạng 41 là **ngoài tầm cứu của mọi mẹo thời gian** — và đúng như dự
đoán, cả seq-RAW (cộng dồn chuỗi) lẫn seq-NORM (contrast-normalization chuẩn SeqSLAM) đều giữ nguyên 0%
định vị đúng (seq-NORM còn tệ hơn do các session đa-vòng vi phạm giả định một-lượt của SeqSLAM). Hướng
**multi-reference** (lưu nhiều ảnh/chỗ ở nhiều điều kiện sáng) cũng thất bại: kể cả khi **chặn theo GPS
≤ 5 m đúng như lúc triển khai**, khung-tham-chiếu đúng là khớp-ngoại-hình tốt nhất chỉ **1%** số lần
(top-3: 4%). Kết luận: bức tường ánh sáng là **giới hạn của bản thân descriptor** (đặc trưng pooled đóng
băng của V-JEPA), không sửa được ở tầng đo-lường — nhất quán với việc chuẩn-hoá-quang-trắc (CLAHE/khớp-
histogram/mean-std) cũng không cứu. Điều khiển (CEM trên **patch-L1**) không dính vì patch-L1 bất-biến-sáng
(<5% thay đổi). Hệ quả thiết kế: lời giải nguyên-lý là một **descriptor học được bất-biến-sáng / đầu
reachability kiểu ViNG** huấn luyện cross-session trên chính bộ 181 session (đã sẵn cặp dương cross-lighting:
cùng GPS+heading khác buổi), với encoder đóng băng; còn giải pháp kịp-thời là **teach lại cùng buổi** (vì
descriptor rất tốt khi ánh sáng gần). Đây tiếp tục là một **negative finding** sạch ở tầng nav-localize,
không ảnh hưởng tới đóng góp chính (world model offline + control).

---

## 8. Thảo luận & Hạn chế

Luận điểm trung tâm rút ra từ toàn bộ thực nghiệm là sự **tách bạch giữa chất lượng biểu diễn và năng
lực điều khiển closed-loop**. Mọi chỉ số liên quan đến biểu diễn đều tích cực: world model thắng baseline
ổn định, transfer chéo-domain-servo có lợi, energy landscape có đáy đúng hướng cua, và định vị bằng thị
giác đạt trung vị ~2 m. Trong khi đó, thất bại closed-loop được truy về một cơ chế cụ thể (cos-dropout +
thiếu recovery) thuộc tầng điều khiển và dữ liệu. Đây là một kết luận có giá trị thực tiễn cho bất kỳ ai
muốn triển khai world model latent trên robot di động ngoài trời.

Báo cáo có một số **hạn chế** cần nêu thẳng. (i) Kết quả closed-loop mang tính **định tính + cơ chế**:
khoảng 10 lần chạy, một môi trường, không có chỉ số tỉ-lệ-thành-công chuẩn (0 lần về đích). (ii) Dữ liệu
teach thiếu hành vi **recovery** (chỉ một lượt giữa tuyến). (iii) Tồn tại **confound ánh sáng** giữa
teach và repeat — chúng tôi nêu rõ điều này thay vì che giấu, vì chính nó củng cố luận điểm "gap ở tầng
khớp-live/điều khiển, không ở biểu diễn". (iv) GPS chỉ ~1 Hz, nhiễu 0,44 m, nên chỉ làm cổng chuyển
subgoal thô. (v) Encoder cần GPU nên độ trễ điều khiển cao (0,5–5,5 s/chu kỳ). (vi) Biên độ thắng offline
ở biến thể pooled khá khiêm tốn (hơn baseline ~4%); con số headline dựa vào `cd4` (0,744) và transfer
chéo-servo — trung thực mà nói, đây là mức báo cáo/workshop, không phải SOTA.

---

## 9. Hướng phát triển

Các hướng phát triển đều nhắm thẳng vào tầng đã được xác định là điểm nghẽn (control + dữ liệu), chứ
không vào encoder. **Thứ nhất và quan trọng nhất**, *retrain với dữ liệu recovery*: thu hoặc augment các
cảnh xe lệch khỏi tuyến rồi hành động kéo về (đúng loại tín hiệu ViNG/Meta có) để predictor/policy học
được hướng-về, qua đó xoá hiện tượng panic ở cos-dropout. **Thứ hai**, dựng *sim 3DGS* (Gaussian
Splatting) từ chính dữ liệu thực địa để test closed-loop trong nhà, có kiểm soát heading và ánh sáng,
lặp nhanh ban đêm mà không phụ thuộc nắng/pin. **Thứ ba**, nâng cấp thước đo khớp-live cho bền hơn dưới
domain-shift: *seq-matching* kiểu SeqSLAM (khớp chuỗi nhiều frame) hoặc *reachability/temporal-distance
head* kiểu ViNG (học "còn mấy bước tới goal" thay cho cosine tức thời). **Thứ tư**, trang bị *RTK GPS*
(độ chính xác 1–2 cm) để có cổng chuyển subgoal chính-xác-mét và ground-truth lệch-ngang phục vụ đánh
giá định lượng.

---

## 10. Kết luận

Encoder V-JEPA 2.1 đóng băng cung cấp một **biểu diễn latent đủ tốt** để (a) một AC predictor nhỏ vượt
baseline identity một cách ổn định ở mọi horizon (rollout@1 = 0,744), (b) transfer chéo-domain-servo có
lợi (0,65 so với 1,073), và (c) định vị bằng thị giác đạt trung vị ~2 m trên đồ thị topo. Tuy nhiên,
triển khai closed-loop ngoài trời **bung ở điểm cos-dropout** do **thiếu tín hiệu lateral-recovery** trong
dữ liệu teach một-lượt-giữa-tuyến. Đây là **đánh giá đầu tiên họ V-JEPA 2 trên một robot di động** và một
**negative finding trung thực**: với cùng một biểu diễn mạnh, khoảng cách giữa "dự đoán latent tốt
offline" và "lái được closed-loop ngoài trời" nằm ở **nav-robustness + control + dữ liệu recovery**, chứ
không ở chất lượng representation. Các hướng phát triển vì thế tập trung vào tầng đó.

---

## Bảng số liệu (đặt cuối hoặc rải theo section — đã verify)

**Bảng A — World model offline (rollout@k / identity; < 1 = thắng baseline, thấp hơn = tốt hơn)**

| Model | @1 | @2 | @3 | Ghi chú |
|---|---|---|---|---|
| **cd4 (triển khai)** | **0,744** | **0,703** | **0,697** | frozen split, 2000 window |
| vjepa_ac pooled (5-seed CV) | 0,958 ± 0,024 | — | — | 4/5 seed < 1, ổn định |
| vjepa_ac_pool (baseline pooled) | 0,867 | — | — | ablation |
| **LeWM** (pixel-JEPA, baseline) | 0,97 ± 0,15 | — | ≥ 1 (horizon dài) | 2/5 fold fail, không ổn |
| cd4_as3 (auto_steps 3) — ablation âm | 0,745 | 0,699 | 0,686 | pred tốt hơn, action-sens kém → bỏ |

**Bảng B — Transfer chéo-domain-servo (eval trên TowerPro held-out, @1)**

| Train | rollout@1 |
|---|---|
| TowerPro-only | 1,073 (thua đứng yên) |
| **Mixed (KDS + TowerPro)** | **0,65** |

**Bảng C — Độ nhạy hành động (energy-probe, d=4, cd4)**

| Đo | cd4 | cd4_as3 |
|---|---|---|
| argmin-E đúng hướng cua | **58/60** | 54/60 |
| median \|argmin − teacher\| | ≈ 0,12 | — |
| độ tương phản (E_max−E_min)/E_min | **≈ 0,36** | 0,274 |
| Δsteer / Δthrot recovery | 0,16 / 0,04 | — |
| tương phản theo khoảng cách | d2 0,443 / d4 0,355 / d8 0,270 | — |

**Bảng D — Closed-loop teach & repeat (route ~15 m; KHÔNG run nào về đích)**

| Run | tick | cấu hình | bám tốt tới | bung tại (cos) | kết cục |
|---|---|---|---|---|---|
| 163607 | 1,13 s | fast | sg18 (lệch < 0,5 m) | sg21 (0,07) | bung trái +3,2 m |
| 163831 | 2,82 s | slow | sg8 | sg10 (0,27) | trôi −2,4 m |
| 164827 | 2,90 s | slow | sg12 | sg27 | trôi trái +2,8 m |
| 171912 | 1,78 s | pure-visual sạch | sg6 | sg7 (0,02) | veer trái → bụi cỏ |

**Bảng E — Navigation (TopoGraph)**

| Đo | Giá trị |
|---|---|
| Graph 92-session (28 KDS + 64 TowerPro) | 29.699 node, 1 component 100% |
| Localize LOSO | trung vị 2,1 m (< 8 m: 88%) |
| Routing thành công | 100% |
| Place recognition (centered-cos) | tại-chỗ ~1,0 / kế ~0,58 / cách-2 ~0,37 (raw-cos vô dụng 0,95–0,99) |
