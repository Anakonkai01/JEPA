# V-JEPA-2-AC cho xe RC — bản thiết kế (grounded từ paper gốc)

> Viết 2026-06-08. Đây là **control model chính** (đóng góp): port trung thực V-JEPA 2-AC của Meta
> sang xe RC di động (Meta chỉ thử trên cánh tay Franka). Mọi tham số đều có dẫn chứng từ paper
> (`docs/*.pdf` → text ở `/tmp/vjepa2.txt`, `/tmp/vjepa21.txt`) và code gốc (`reference/vjepa2/`).
> Bản pooled cũ (`vjepa_ac_pool`) đã hạ thành **baseline** (xem `models/__init__.py`).

## 0. Vì sao thiết kế này (đã verify, KHÔNG suy diễn)

- **Encode TỪNG frame** (image-encoder, nhân đôi theo thời gian cho tubelet-2) → patch map
  `z_k = E(x_k)`, KHÔNG pool, KHÔNG tube nhiều frame (vjepa2.txt:345,551,601).
- **Motion/tốc độ KHÔNG đến từ encoder** mà từ (a) **state token** (proprioception) + (b) predictor
  block-causal trên chuỗi. Thí nghiệm tự đo: latent single-frame pooled có **R²(speed)=−1.1**
  (0 thông tin tốc độ); nhồi clip vào encoder cũng chỉ ~0 → đúng như paper: tốc độ phải vào qua
  **state token**, không phải encoder.
- **Camera xe thấy bánh lái trước** → **góc lái đã nằm trong patch map** (state quan sát được bằng ảnh).
  Nên chỉ cần state token lo phần **tốc độ** (GPS speed) — phần ảnh không cho.
- **V-JEPA 2.1** (ViT-L distilled-từ-ViT-G 384, đang dùng) = Dense Predictive Loss → patch feature
  chất lượng cao (localization/geometry + dynamics) → đúng encoder cho patch-token control.

## 1. Kiến trúc

```
mỗi frame x_k ──[V-JEPA 2.1 ViT-L, FROZEN, per-frame]──► z_k  (patch tokens, N_tok × 1024)
state s_k = [x, y, heading, speed]  (GPS + IMU)         ──┐
action a_k = [steer, throttle]                          ──┤ interleave (a_k, s_k, z_k)
                                                          ▼
                          Predictor block-causal (RoPE) ──► ẑ_{k+1}  (patch tokens)
```

| Thành phần | Giá trị | Nguồn |
|---|---|---|
| Encoder | V-JEPA 2.1 ViT-L 384, frozen, per-frame | hub `vjepa2_1_vit_large_384` |
| Patch grid | **256px → 16×16 = 256 token** (theo Meta AC 256²; nhẹ đĩa hơn 384/576) | vjepa2.txt:541 |
| embed_dim | 1024 | encoder ViT-L |
| State `s_k` | `[x_local_m, y_local_m, heading_rad, speed_mps]` (GPS) +(tùy) gyro_z, ax | `gps.csv`, `imu_synced.csv` |
| Action `a_k` | `[steer, throttle]`, chuẩn hóa per-dim | `actions_synced.csv` |
| Predictor | block-causal transformer, depth **8** (khởi điểm; Meta 24/300M cho ViT-g — ta sweep), heads 16, hidden 1024, 3D-RoPE patch + temporal-RoPE cho a/s | vjepa2.txt:~570 |
| Loss | **L1 teacher-forcing + rollout 2-step** | vjepa2.txt eq.2-4 |
| Planning | CEM, context 2 frame, horizon 4, energy `‖P−z_goal‖₁`, receding-horizon | vjepa2.txt:658-687 |

## 2. State token cho xe (chỗ TỐC ĐỘ vào model)

- `gps.csv` có sẵn `lat, lon, speed (m/s), bearing (deg)`. Chuyển:
  - `x,y` = lat/lon → mét cục bộ (equirectangular quanh điểm đầu session).
  - `heading` = `bearing` (rad).
  - `speed` = cột speed (m/s).
- GPS ~1Hz → nội suy về `t_scene_ms` mỗi frame; (tùy) fuse gyro_z (yaw-rate) + ax (accel dọc) từ
  `imu_synced.csv` ~50Hz cho mượt.
- Chuẩn hóa state per-dim (z-score theo train).

## 3. Lúc planning (CEM) — state tương lai CHƯA quan sát

Paper tích phân state bằng `compute_new_pose(pose, action)` (động học cánh tay). Cho xe = **bicycle-model**
nhỏ tích phân `[x,y,heading,speed]` từ `[steer,throttle]`:
```
speed_{k+1} = speed_k + (k_thr * throttle_k - k_drag * speed_k) * dt
heading_{k+1} = heading_k + (speed_k / L) * tan(k_steer * steer_k) * dt
x_{k+1} = x_k + speed_k*cos(heading_k)*dt ;  y_{k+1} = y_k + speed_k*sin(heading_k)*dt
```
Hệ số `k_thr, k_drag, k_steer, L` **fit từ data thật** (steer/throttle → Δspeed/Δheading đo bằng GPS/IMU).
Đây là **phần kỹ thuật mới-tự-dựng, rủi ro lớn nhất** → cần calib + sanity-check kỹ.

## 4. Bảng so sánh (đóng góp)

| Model | Loại | Vai |
|---|---|---|
| **VJEPA2ACCar** (patch + state + block-causal) | frozen V-JEPA 2.1 + predictor | **ĐÓNG GÓP** |
| `vjepa_ac_pool` | frozen + probe pooled | ablation (patch+state có cần?) |
| LeWM | end-to-end pixel JEPA (LeJEPA/SIGReg) | baseline độc lập mạnh |
| ActionCNN, LSTM | trên latent pool | baseline đơn giản |

Metric: offline rollout-L1 vs identity · Δsteer/**Δthrot** action-recovery · eval_goal_reaching CEM/random
· **closed-loop goal-reaching success thật trên xe** (deliverable cuối).

## 5. Còn MỞ (phải thí nghiệm)
1. Depth/size predictor cho ~125k frame (dễ overfit nếu quá to).
2. Bicycle-model calib (mục 3).
3. GPS 1Hz thô → fuse IMU.
4. Chuẩn hóa action/state per-dim.
5. Tie-in TopoGraph: subgoal-ảnh → AC lái tới từng cái.

## 5b. RÀ SOÁT vs code Meta gốc (`reference/vjepa2/src/models/ac_predictor.py` + paper)

**Khớp (đã verify):**
- Interleave **`[action, state, patch…]` mỗi frame** ✓ (Meta `forward`: `cat([a,s,x])`).
- **Block-causal**: token frame t thấy mọi token frame ≤ t ✓ (test: đổi frame tương lai → frame 0 không đổi).
- Output **chỉ lấy patch slot** (bỏ token cond), norm, proj về `latent_dim` ✓.
- Loss **L1 teacher-forcing + rollout 2-step** ✓ (paper eq.2-4).
- Planning **CEM energy `‖P−z_goal‖₁`, receding-horizon** ✓ (paper §3.2; world_model_wrapper rollout=2).

**Đã SỬA cho khớp Meta (session 2026-06-08 chiều):**
- **Chuẩn hóa rep = per-token LayerNorm** (Meta `F.layer_norm(h,(D,))` trong world_model_wrapper),
  thay global z-score. Bỏ luôn `lat_mean/std` → nhẹ RAM, và **re-LN sau mỗi bước rollout** (Meta normalise
  reps trước khi feed lại).
- **predict_residual=false** (Meta đoán **tuyệt đối** `ẑ=P(...)`, không `z+Δ`). Residual để ablate.

**Lệch CÓ CHỦ Ý (chấp nhận, ghi rõ):**
- **Pos-embedding học được (temporal + token-type)** thay **3D-RoPE** của Meta. RoPE tổng quát hơn theo
  vị trí/độ-dài; với clip nhỏ cố định thì pos học được đủ. → nâng cấp RoPE sau nếu cần.
- **State = [speed,gx,gy,gz,ax,ay,az]** (IMU+GPS, 7-D — trùng số chiều Meta) thay pose 7-D cánh tay; bỏ vị
  trí tuyệt đối (overfit địa điểm). dynamics tích phân **[speed,yaw_rate]** bằng bicycle-model (analog
  `compute_new_pose`).
- **Depth 8 / pred_dim 512 / 26M** thay 24-layer/300M của Meta (data ta ~125k frame, tránh overfit; sweep sau).

## 5c. Vấn đề RAM (đã sửa) + faithful normalization
- RAM máy **30GB**, session dài tới **4GB token** → lru cache nhiều session = OOM. **Sửa:** cache `.npy`
  **memmap** (đọc đúng vài row/window, không nạp cả session) + `SessionBatchSampler` (giữ cache nóng) +
  bỏ `_patch_stats` (LN thay z-score) → RAM phẳng.

## 5d. CHỐT 2026-06-08 (với user) — đính chính resolution + state

**Resolution (đã verify lại paper, tôi từng nói SAI):**
- **384 là cố ý cho CHẤT LƯỢNG** — V-JEPA 2 dòng 313 "256→384 ... improvement"; V-JEPA 2.1 cooldown ở
  **384** (dòng 361-362), checkpoint ViT-L distilled là **384-native**.
- **256 của V-JEPA 2-AC = lựa chọn COMPUTE** (clip 16-frame cho MPC planning, "for simplicity"), KHÔNG
  phải "256 đẹp hơn". → gọi 256 "faithful" là sai.
- **Quyết:** **iterate ở 256** (rẻ, ablate nhanh — 384 chậm ~5× vì token 256→576/frame), **chốt model
  cuối ở 384**. fp16 cache giữ (sai số không đáng kể). ViT-G = ablate riêng (frozen → rẻ, train không chậm
  hơn; Meta-AC thật dùng giant).

**State = full IMU (10-D):** `[speed, gx,gy,gz, ax,ay,az, rx,ry,rz]` = GPS speed + gyro + accel +
rotvec(orientation). "Dùng hết rồi ABLATE vs [speed,gz]". accel: gravity là hằng → z-score khử; rotvec:
pitch/roll = tư thế xe. **Loại** lat/lon/alt/bearing (vị trí tuyệt đối = overfit địa điểm). CEM dynamics
tích phân speed+yaw(gz); các kênh còn lại hold-last (horizon ~1s).

## 6. Thứ tự build (file dự kiến)
1. `engine/encode_patch.py` → `data/latents_<set>_patch/*.pt` (patch token fp16, 256px).
2. `data/state.py` → state vector per-frame từ gps/imu.
3. `models/vjepa2_ac_car.py` → predictor block-causal (port adapt).
4. `data/dataset.py::ACClipDataset` → cửa sổ clip (patch, state, action).
5. `engine/train_ac_car.py` → L1 teacher-forcing + rollout.
6. `planning/dynamics.py` → bicycle-model integrator.
7. `planning/cem.py::CEMPlannerAC` → energy L1 patch + state rollout.
8. eval: mở rộng `eval_goal_reaching.py`.
