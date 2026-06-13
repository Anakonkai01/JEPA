# Kế hoạch SIM closed-loop bằng 3D Gaussian Splatting (3DGS) — SAU deadline 06-15 / cho paper

> Viết 2026-06-13. Đây là **khoản đầu tư SAU deadline** (deadline 06-15 thì dùng Phase-4 +
> sim-động-học đã có + 1 buổi bãi — xem `HANDOFF.md` 06-13). Doc này để dành, không chạy gấp.
>
> **Vì sao 3DGS, không Isaac/Cosmos?** Đánh giá đầy đủ + nguồn ở cuối. Tóm: 3DGS dựng cảnh THẬT
> của park từ data MÌNH đã có → đóng vòng trên **đúng pipeline V-JEPA+AC+CEM** trong **đúng domain**,
> chạy nhẹ trên RTX 5070 Ti. Isaac = render tổng hợp (visual gap) + overkill. Cosmos = world-model
> pixel quá nặng (16GB không kham) + không có ground-truth hình học → chỉ hợp augmentation/paper.

## ▶️ NEXT SESSION — EXECUTION CHECKLIST (chạy theo thứ tự, mỗi bước 1 GATE)

> **Môi trường ĐÃ KIỂM 06-13 (máy pc5070ti):** COLMAP **CHƯA cài** · nerfstudio/gsplat **CHƯA cài** ·
> GPU **RTX 5070 Ti 16GB, CUDA 12.8, torch 2.10.0+cu128** (cuda avail ✓) · session mẫu
> `data/raw_towerpro/session_20260607_124454` = **5310 frame**, gps 624 dòng, rotvec 32311 dòng.
> → Bước 0 PHẢI cài trước. Mọi bước viết script vào `scripts/sim3dgs_*.py` (durable, commit).

**Bước 0 — Cài (1 lần):**
```bash
sudo pacman -S colmap                                   # Arch extra: SfM ra pose
~/miniforge3/envs/ai/bin/pip install nerfstudio         # kéo theo gsplat (build CUDA ext theo torch 2.10/cu128)
colmap -h | head -1 && ~/miniforge3/envs/ai/bin/python -c "import gsplat, nerfstudio; print('gs OK')"
```
GATE 0: `colmap` chạy + `import gsplat` OK. (gsplat lỗi build cu128 → `pip install gsplat` riêng,
hoặc fallback 3DGS gốc graphdeco-inria. nerfstudio nặng dep → cân nhắc env riêng `gs` nếu đụng torch.)

**Bước 1 — Trích frame** (`scripts/sim3dgs_extract.py`): chọn session ĐÃ chạy tuyến cần test (vd tuyến
park4 chiều 06-13; mẫu nhiều coverage = `session_20260607_124454`). 5310 frame quá nhiều cho SfM →
**subsample mỗi ~4** (~1300), **bỏ frame đứng** (gps speed<0.3 → trùng view) + **lọc blur**
(Laplacian-var thấp). → GATE 1: ~800–1500 ảnh sắc nét phủ tuyến trong `/tmp/gs_park/images/`.

**Bước 2 — Pose (COLMAP)** → chi tiết §2-B1. `sequential_matcher` (frame tuần tự + park TỰ-GIỐNG dễ
loop sai) + Umeyama khớp quỹ đạo GPS lấy **scale mét** + canh về graph-frame. → GATE 2: reproj
< ~1.5px, >80% ảnh registered, quỹ đạo COLMAP khớp hình GPS (kiểm chéo heading bằng rotvec như Gate-0).

**Bước 3 — Train 3DGS** → §2-B2 (`ns-train splatfacto`, cân nhắc appearance-embedding cho lệch sáng).
→ GATE 3: render dọc tuyến ra cảnh park (mắt thường) + PSNR hold-out ổn.

**Bước 4 — Harness closed-loop** → §2-B3. **Refactor lõi quyết-định `inference_loop.main` thành hàm
`plan_tick(rgb, meta, state…)`** để CẢ xe thật LẪN `scripts/sim3dgs_loop.py` gọi (1 nguồn logic).
Inject GPS-1Hz + rotvec noise. → GATE 4: tái hiện hành vi park (visual-servo trôi / geosteer hội tụ)
≈ xe thật → SIM dùng được để A/B + tune CEM.

> ⚠ Việc này SAU khi đã triage log test bãi chiều 06-13 (xem `HANDOFF.md` §9) — bãi là deadline-path,
> 3DGS là đầu-tư-dài. Nhưng refactor `plan_tick` (Bước 4) có thể làm SỚM vì có ích cho cả hai.

## 0) Bài toán SIM giải được mà sim-động-học (bicycle) KHÔNG

| | sim-động-học (đã có: `geosteer_validate.py`) | 3DGS closed-loop (doc này) |
|---|---|---|
| Render ảnh camera xe | ❌ không | ✅ photoreal, free-viewpoint |
| Test controller (Stanley) ổn định | ✅ | ✅ |
| Test V-JEPA `cos`-collapse / lệch sáng | ❌ | ✅ (đóng vòng perception thật) |
| Test CEM (samples/iters/horizon) định lượng | ❌ | ✅ (có ground-truth frame tương lai) |
| Test AC-predictor rollout chính xác | ❌ | ✅ (so latent dự đoán vs render thật) |
| Lặp lại ban đêm, không cần ra park | ✅ | ✅ |

→ 3DGS = nơi DUY NHẤT test được **toàn bộ stack** (tri-giác + nav + control) closed-loop ngoài xe thật.

## 1) Dữ liệu đầu vào (ĐÃ CÓ)
- `data/raw_towerpro/session_*` — **175+ session** có `frames/*.jpg` + `gps.csv`(lat,lon,speed,bearing) +
  `rotvec.csv`(rx,ry,rz 50Hz) + `imu_synced.csv`. Chọn **1–2 session phủ tuyến cần test** (vd các
  session park đã teach route park4/park3).
- Lưu ý: 3DGS cần **pose camera** (extrinsics + intrinsics). GPS 1Hz quá thô làm pose trực tiếp →
  phải chạy **SfM (COLMAP)**; GPS+rotvec dùng để **seed + lấy SCALE mét** (3DGS/COLMAP vô-scale).

## 2) Pipeline dựng (3 bước)

### B1 — Pose: COLMAP SfM trên frames
```
# trích frame (mỗi ~3–5 frame/lấy 1 để SfM nhanh, tránh blur — dùng dcam/exposure đã lọc)
colmap feature_extractor  --image_path frames/ --database_path db.db
colmap exhaustive_matcher --database_path db.db          # hoặc sequential_matcher (video tuần tự → nhanh hơn)
colmap mapper             --image_path frames/ --database_path db.db --output_path sparse/
# → sparse/0/ : poses + intrinsics + sparse point cloud (vô-scale)
```
- **Scale mét:** khớp quỹ đạo COLMAP (vô-scale) với GPS xy (mét) bằng Umeyama/Procrustes (similarity
  transform) → ra hệ số scale + xoay/tịnh tiến về graph-frame. Cách khác: dùng rig-prior GPS trong
  `colmap`/`glomap` nếu hỗ trợ. **Rotvec** kiểm chéo heading từ pose (giống Gate-0 đã làm).
- Khó khăn thật: park **tự-giống** (cỏ/đường lặp) → matcher dễ nhầm; ảnh xe rung/blur. Mitigations:
  `sequential_matcher` (ưu tiên frame kề thời gian), lọc frame blur, dùng GPS-prior chặn loop-closure sai.

### B2 — Train 3DGS
- Công cụ chạy tốt trên RTX 5070 Ti 16GB (chọn 1):
  - **nerfstudio `splatfacto`** (dễ nhất, có `ns-process-data` bọc COLMAP) — KHUYÊN bắt đầu.
  - **`gsplat`** (thư viện rasterizer của nerfstudio, nhanh) hoặc 3DGS gốc (graphdeco-inria).
  - Outdoor/park rộng → cân nhắc **appearance-embedding** (per-image, kiểu "Splatfacto-W /
    Gaussian-in-the-Wild") để model đổi sáng giữa frame — đúng bài toán lệch-sáng của mình.
```
ns-process-data images --data frames/ --output-dir gs_park/   # bọc COLMAP
ns-train splatfacto --data gs_park/                            # train vài phút–1h, render >100 FPS
```
- Output: model 3DGS render được **góc-nhìn camera-xe từ pose bất kỳ** quanh tuyến.

### B3 — Harness closed-loop (script mới, vd `scripts/sim3dgs_loop.py`)
Thay `FrameReader` (TCP phone) bằng **renderer 3DGS**; phần còn lại (V-JEPA encode + nav + CEM +
controller + geosteer) dùng **NGUYÊN inference_loop** (tái sử dụng, không fork logic điều khiển):
```
khởi tạo: pose xe (x,y,yaw) trong frame 3DGS = đầu route teach; load route tay (park4) như inference.
mỗi tick:
  1. render = gaussians.render(camera_from(x,y,yaw, intrinsics))      # ảnh RGB cam-xe
  2. meta   = {lat,lon ← (x,y)+GPS-noise 1Hz giữ-mẫu, rx,ry,rz ← yaw+OFFSET+rotvec-noise, speed,…}
  3. action = pipeline(render, meta)   # encode → nav subgoal → CEM/geosteer → [steer,throt]  (HÀM CHUNG)
  4. (x,y,yaw) = bicycle_step(action, CarDynamics đã fit)            # động học THẬT (k_thr/k_drag/k_yaw)
  5. log cross-track, cos, subgoal-idx, recovery-fire
```
- **Inject đúng nhiễu thật:** GPS 1Hz (noise ~0.44m, giữ giữa mẫu) + rotvec (offset đổi mỗi "buổi" +
  noise ~10°, đo Gate-0) → tái hiện đúng điều kiện closed-loop mà sim-động-học + xe thật gặp.
- **Tách hàm:** refactor lõi quyết-định inference thành 1 hàm `plan_tick(rgb, meta, state…)` để CẢ
  `inference_loop.py` (xe thật) LẪN `sim3dgs_loop.py` gọi — 1 nguồn logic, sim test đúng cái chạy thật.

## 3) Thí nghiệm + metric (cổng, như geosteer)
1. **Route-follow:** thả xe đầu park4 → chạy tới cuối. Metric: %tuyến hoàn thành, **cross-track
   trung vị/max**, số lần recovery-fire, có xoay vòng không. (Tái hiện được lỗi 06-13 trong sim?)
2. **cos-collapse:** đo `cos` control-target dọc tuyến — chỗ nào sập (cua? đổi sáng?) → đối chiếu lỗi bãi.
3. **Lệch sáng:** train 3DGS session sáng A, render với appearance của buổi B → đo `cos` tụt bao nhiêu
   → định lượng bug "re-teach mỗi buổi" + thử fix (CEM threshold / augmentation).
4. **Tune CEM:** với ground-truth frame tương lai (render pose sau khi áp action), so latent AC-predict
   vs render thật → chọn samples/iters/horizon TỐT NHẤT bằng SỐ (thay vì vặn nút ở bãi).
5. **A/B recovery:** geosteer (Phase 4) vs visual-servo trần vs v1 — closed-loop trong sim, đo hội tụ.

## 4) Caveat (phải ghi rõ, không over-claim)
- **Cảnh TĨNH:** không người/xe/lá bay; phản chiếu/trời/nền xa render kém. OK cho teach-repeat tuyến cố định.
- **Pose/scale:** sai số COLMAP + scale-từ-GPS → có gap hình học; phải kiểm (reproj error, so GPS).
- **Appearance cố định** lúc quay (trừ khi dùng appearance-embedding / Cosmos-Transfer relight).
- **Novel-view xa tuyến** (xe lệch 5m+) render xuống cấp — nhưng recovery chỉ cần quanh tuyến nên ít hại.
- Sim-to-real **động học** vẫn từ bicycle/CarDynamics (đã fit), không phải PhysX → giữ nguyên giả định.
- ⚠ Sim **KHÔNG xoá** Rủi ro #1 (dấu steer→yaw trên xe) — vẫn phải canh với xe (divergence-detector + bãi).

## 5) Công sức + thứ tự
- COLMAP 1 session + splatfacto: ~0.5–1 ngày (lần đầu, gồm vật lộn pose park tự-giống).
- Harness closed-loop + refactor `plan_tick`: ~1–2 ngày.
- Thí nghiệm + viết: ~1–2 ngày. **Tổng ~1 tuần** → SAU 06-15.

## 6) Cosmos / Isaac — vai trò (đã web-check 06-13)
- **NVIDIA Cosmos 3** (ra COMPUTEX 2026, Jensen Huang — "Open Frontier Foundation Model for Physical
  AI", gộp vision-reasoning + sinh đa-mô-thức text/video/image/audio/**action**): **KHÔNG** dùng làm
  sim-validate (quá nặng cho 16GB, không có GT hình học). **CÓ** giá trị: (a) **Cosmos-Transfer** nhận
  segmentation/depth/lidar/**pose/trajectory map** → sinh video photoreal có điều khiển = **augmentation/
  relight** cho bug lệch-sáng + sinh data tổng hợp; (b) **điểm so sánh paper** (latent world model V-JEPA-AC
  nhẹ vs pixel world model Cosmos nặng).
- **Isaac Sim/Lab** (GTC 2026: Onshape→Isaac CAD-to-sim, sensor-physics nâng cao): overkill cho teach-
  repeat 1 xe — vật lý đã có bicycle, render tổng hợp tạo visual-gap. **Bỏ qua.**
- **Tiền lệ 3DGS closed-loop AD (đúng hướng này):** **HUGSIM** (real-time photoreal closed-loop AD sim
  bằng 3DGS), **GaussianRPG** (open-source AD closed-loop, v2.0 hardware-in-the-loop), **SplatAD**
  (render camera+lidar bằng 3DGS) → có precedent + code tham khảo.

## 7) Nguồn
- 3DGS gốc: Kerbl et al., SIGGRAPH 2023 · nerfstudio `splatfacto` + `gsplat` · COLMAP (SfM).
- HUGSIM: https://huggingface.co/papers/2412.01718
- GaussianRPG: https://github.com/GimpelZhang/GaussianRPG
- NVIDIA Cosmos: https://www.nvidia.com/en-us/ai/cosmos/ · Cosmos 3: https://blogs.nvidia.com/blog/cosmos-3-physical-ai-open-world-foundation-model/
- Isaac Sim 2026: https://developer.nvidia.com/blog/advanced-sensor-physics-customization-and-model-benchmarking-coming-to-nvidia-isaac-sim-and-nvidia-isaac-lab/
