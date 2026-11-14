# 统计口径契约（metrics contract）

> **本文件是移动端统计算法的单一真相源。**
>
> 移动端的目标不是"自己发明一套算法"，而是**继承 fit_analyzer 桌面端经 13 个版本
> 打磨的正确实现**。任何算法改动必须先更新本文件，再改代码。

---

## 为什么必须自己算，不能信 FIT 文件自带值

FIT 文件里有 `session.total_ascent`、`session.total_moving_time` 这类汇总字段。
**不能用它们**，原因：

1. **各厂商算法不同** —— 同一个爬升，佳明、iGPSPORT、Wahoo 算出的值可以差 10%+
2. **噪声处理策略不同** —— 有的把 ±0.3 m 的气压计抖动全累加，数值明显偏大
3. **口径不透明** —— 你不知道厂商用了什么滤波

所以桌面端选择**自己从逐点记录算**。移动端照做。

---

## 常量表（必须逐字一致）

| 常量 | 值 | 定义位置（桌面端） | 定义位置（移动端） | 含义 |
|---|---|---|---|---|
| `ALTITUDE_NOISE_THRESHOLD_M` | `1.0` | `core/analysis.py` | `lib/core/stats/metrics.dart` | 海拔噪声阈值（米） |
| 移动速度阈值 | `0.5` | `core/analysis.py::moving_time` | `movingSpeedThresholdMs` | m/s，> 视为移动 |
| 区间 dt 上限 | `30.0` | `core/analysis.py::_weighted_zone_times` | `maxZoneDtSeconds` | 秒 |
| 曲线抽稀点数 | `600` | `core/analysis.py::downsample_series` | `defaultSeriesMaxPoints` | 点 |
| 轨迹抽稀点数 | `2000` | `core/analysis.py::track_points` | `defaultTrackMaxPoints` | 点 |
| 心率区边界 | `[0.6, 0.7, 0.8, 0.9]` | `core/training_load.py::_lactate_zones_pcts` | `hrZonePcts` | 最大心率百分比 |
| 心率区 IF 映射 | `[0.50, 0.65, 0.75, 0.85, 0.95]` | `core/training_load.py::_tss_from_hr` | `hrZoneIntensityFactors` | 等效强度因子 |
| CTL 时间常数 | `42.0` | `core/training_load.py::CTL_TAU` | `ctlTau` | 天 |
| ATL 时间常数 | `7.0` | `core/training_load.py::ATL_TAU` | `atlTau` | 天 |
| 估算功率：重力加速度 | `9.80665` | `core/analysis.py::estimate_power` | `estimate_power.dart::_g` | m/s² |
| 估算功率：平滑窗口 | `5` | 同上（硬编码 `W`） | `_smoothWindow` | 点 |
| 估算功率：坡度上限 | `±0.25` | 同上 | `_maxGrade` | 比率 |
| 估算功率：加速度上限 | `±1.5` | 同上 | `_maxAccel` | m/s² |
| 估算功率：人体重 | `70.0` | `core/config.py` | `PowerEstimateConfig.riderWeightKg` | kg |
| 估算功率：车重 | `10.0` | 同上 | `bikeWeightKg` | kg |
| 估算功率：Crr | `0.005` | 同上 | `crr` | — |
| 估算功率：CdA | `0.35` | 同上 | `cda` | m² |
| 估算功率：空气密度 | `1.225` | 同上 | `airDensity` | kg/m³ |

**改动任一个值 = 破坏口径一致性。** 若桌面端确实要改，移动端必须同步改 + 更新本文件。

---

## 指标契约

### 1. 爬升 / 下降

| 项 | 内容 |
|---|---|
| 桌面端 | `core/analysis.py::accumulate_ascent_descent` |
| 移动端 | `lib/core/stats/analysis.dart::accumulateAscentDescent` |
| 算法 | **滞回参考点法** |

**伪码（跨语言比对的唯一形式）：**
```
ref = None
ascent = descent = 0
for ele in eles:
    if ele is None: continue
    if ref is None: ref = ele; continue
    d = ele - ref
    if d >= THRESHOLD:
        ascent += d
        ref = ele
    elif d <= -THRESHOLD:
        descent += -d
        ref = ele
```

**为什么不用朴素算法：** 朴素「正增量全加」会把 ±噪声全部累成爬升。举例：
`[100, 100.5, 100, 100.5, 100, 100.5]` —— 朴素算法得出 ascent=1.5（3 次 0.5），
滞回法得出 ascent=0（每次变化都不足 1.0 阈值）。真实爬升不会这么抖动。

**金标准测试用例：**
```
eles = [100, 100.5, 101.8, 101.2, 102.5, 103.0, 102.0, 104.5, 99.0]
→ ascent = 5.5, descent = 6.5
```

---

### 2. 移动时间

| 项 | 内容 |
|---|---|
| 桌面端 | `core/analysis.py::moving_time` |
| 移动端 | `lib/core/stats/analysis.dart::movingTime` |
| 算法 | speed > 0.5 m/s 视为移动，累加相邻时间差 |

**伪码：**
```
mt = 0
for i in range(len(records)):
    if records[i].speed > 0.5:
        dt = 1.0
        if i+1 < len(records):
            dt = max(0, records[i+1].t - records[i].t)
        mt += dt
return mt
```

**注意：** 最后一条记录没有"下一条"，dt 取 1.0。

**注意：** 与 FIT 的 `total_moving_time` 不同，与用 `events`（暂停/恢复）算的也不同。
这是桌面端口径。

**金标准测试用例：**
```
speed = [0.0, 3.0, 5.0, 0.3, 4.0], t = [0, 5, 10, 15, 20]
→ moving_time = 11.0
（索引 1: dt=5，索引 2: dt=5，索引 4: 最后一条 dt=1.0）
```

---

### 3. 区间时间（加权）

| 项 | 内容 |
|---|---|
| 桌面端 | `core/analysis.py::_weighted_zone_times` |
| 移动端 | `lib/core/stats/analysis.dart::weightedZoneTimes` |
| 算法 | 按相邻记录时间差加权 |

**伪码：**
```
zones = [0] * (len(boundaries) + 1)
for i in range(len(records)):
    v = records[i][value_key]
    if v is None: continue
    dt = 1.0
    if i+1 < len(records):
        dt = max(0, min(records[i+1].t - records[i].t, 30.0))
        if dt == 0: dt = 1.0
    idx = 0
    for b in boundaries:
        if v >= b: idx += 1
        else: break
    zones[idx] += dt
```

**为什么按时间加权：** 简单计数（每条算 1 秒）在记录间隔不均时会失真。
比如设备每秒记录一次 vs 每 5 秒记录一次，计数法会严重偏向记录密的区间。

**dt 上限 30 秒的原因：** 长间隔（如信号丢失）不应被当成"在该区间停留了很久"。

**金标准测试用例：**
```
max_hr=180, hr=[100,115,130,145,165,175,120], t=[0,4,8,12,16,20,24]
boundaries=[108,126,144,162]
→ z1=4.0, z2=5.0, z3=4.0, z4=4.0, z5=8.0（total=25）
pct = [16.0, 20.0, 16.0, 16.0, 32.0]
```

---

### 4. 曲线抽稀

| 项 | 内容 |
|---|---|
| 桌面端 | `core/analysis.py::downsample_series` |
| 移动端 | `lib/core/stats/analysis.dart::downsampleSeries` |
| 算法 | 等间隔索引采样 |

**伪码：**
```
pts = [(r.t, r[key]) for r in records if r[key] is not None]
if len(pts) <= max_points: return pts
step = len(pts) / max_points          # 注意：不是 (n-1)/(m-1)
out = []
for i in range(max_points):
    idx = min(len(pts)-1, int(i * step))
    out.append(pts[idx])
```

**注意：** 与 `track_points` 的采样公式**不同**（后者用 `(n-1)/(m-1)` 且 round）。
不要"统一"这两个公式 —— 那是偏离桌面端。

**金标准测试用例：**
```
1000 个点，max_points=100 → step=10
第一个 idx=0（t=0），最后 idx=min(999, 99*10=990) = 990
```

---

### 5. 按公里分桶

| 项 | 内容 |
|---|---|
| 桌面端 | `core/analysis.py::per_km` |
| 移动端 | `lib/core/stats/analysis.dart::perKm` |
| 分桶键 | `int(dist_m // 1000)` |

**关键：** 分桶用**下取整**。dist=1000 属于 km=1 桶，不属于 km=0。

每桶内：
- `time_s` = 桶内末点 t − 首点 t
- `avg_speed_kmh` = 桶内 (末 dist − 首 dist)/1000 / dt × 3600
- `max_speed_kmh` = 桶内速度最大值 × 3.6
- `avg_hr` / `avg_cad` / `avg_alt` = 桶内均值

---

### 6. 轨迹抽稀

| 项 | 内容 |
|---|---|
| 桌面端 | `core/analysis.py::track_points` |
| 移动端 | `lib/core/stats/analysis.dart::trackPoints` |
| 算法 | 均匀采样 + **保证首尾** |

**伪码：**
```
pts = [(lat, lon, alt) for r in records if r.lat is not None and r.lon is not None]
if len(pts) <= max_points: return pts
step = (len(pts) - 1) / (max_points - 1)
out = [pts[int(round(i * step))] for i in range(max_points)]
if out[-1] != pts[-1]: out[-1] = pts[-1]     # 保证末尾
```

**注意** 这里的 step 公式与 `downsample_series` 不同（见 §4）。

---

### 7. NP 归一化功率

| 项 | 内容 |
|---|---|
| 桌面端 | `core/training_load.py::normalized_power` |
| 移动端 | `lib/core/stats/training_load.dart::normalizedPower` |
| 算法 | 30 秒滚动平均 → 四次方 → 均值 → 开四次方 |

**伪码：**
```
powers = [r.power for r in records if r.power is not None]
if not powers: return None, None
avg = sum(powers) / len(powers)
window = min(30, len(powers))
smoothed = []
for i in range(len(powers)):
    win = powers[max(0, i-window+1) : i+1]
    smoothed.append(sum(win)/len(win))
mean_fourth = sum(p**4 for p in smoothed) / len(smoothed)
np_val = mean_fourth ** 0.25
return round(np_val, 1), round(avg, 1)
```

**注意：** 滚动窗口是**尾部窗口**（含当前点，向前取），不是居中窗口。

**金标准测试用例：**
```
power = [200,220,240,260,180,210,230,250,190,205]
→ NP = 218.4, avg = 218.5
```

---

### 8. TSS

| 项 | 内容 |
|---|---|
| 桌面端 | `core/training_load.py::compute_activity_tss` |
| 移动端 | `lib/core/stats/training_load.dart::computeActivityTss` |
| 优先级 | 功率计 FTP TSS > 心率 hrTSS > null |

**★ 关键约束：估算功率不得用于 TSS。**

```
has_power = any(r.power is not None and not r.powerEstimated for r in records)
```

估算功率（`estimate_power` 从速度/海拔推算）误差过大，用于 TSS 会得出荒谬结果。
因此只要记录的功率全是估算的，就必须走心率降级路径。

**功率 TSS 公式：**
```
IF = NP / FTP
TSS = (seconds × NP × IF) / (FTP × 3600) × 100
```
其中 `seconds = max(t) - min(t)`（用首尾时间戳）。

**心率 TSS（hrTSS）公式：**
```
每档心率区映射 IF:  Z1→0.50, Z2→0.65, Z3→0.75, Z4→0.85, Z5→0.95
TSS = Σ(每区时长小时 × IF²) × 100
```

---

### 9. CTL / ATL / TSB

| 项 | 内容 |
|---|---|
| 桌面端 | `core/training_load.py::_ewma_daily` / `build_performance_curve` |
| 移动端 | `lib/core/stats/training_load.dart::buildPerformanceCurve` |
| 算法 | 指数加权移动平均，α = 1 − exp(−1/τ) |

**★ 关键：空档天数也参与衰减。**

```
for date_str, tss in daily_tss:
    if prev is None:
        prev = tss; prev_date = d
    else:
        gap_days = (d - prev_date).days
        for _ in range(max(0, gap_days - 1)):   # 中间缺失的整天
            prev = prev + alpha * (0 - prev)     # tss=0 推进
        prev = prev + alpha * (tss - prev)
        prev_date = d
```

**为什么重要：** 如果不算空档，数月的训练空档会让 CTL/ATL 错误地保持高位，
导致 TSB 计算完全失真（该休息时显示状态良好）。

**TSB = CTL − ATL**（桌面端用当日值近似）。

---

### 10. 月度统计

| 项 | 内容 |
|---|---|
| 桌面端 | `core/month_agent.py::_month_overview` |
| 移动端 | `lib/core/stats/month.dart::monthOverview` |

**★ 特别注意「平均速度」有歧义 —— 桌面端提供两个值：**

| 字段 | 公式 | 含义 |
|---|---|---|
| `avg_speed_kmh` | 各活动均速的**算术平均** | 每场骑行权重相同 |
| `weighted_avg_speed_kmh` | `Σ(均速×距离)/Σ距离` | 长距离骑行权重更高 |

**UI 必须标注用的是哪个。** 建议主显加权平均（更符合骑行者直觉），
但要在 UI 上写明（如「加权平均速度」）。

**其他口径：**
| 指标 | 口径 |
|---|---|
| `count` | 活动条数 |
| `distance_km` | `Σ total_distance_m / 1000`，1 位小数 |
| `hours` | `Σ timer_s / 3600`，1 位小数 |
| `ascent_m` | `Σ ascent_m`，取整 |
| `calories` | `Σ calories`，取整 |
| `commute` | `commute` 标记拆出的次数/距离 |
| `training_distance_km` | `总距离 − 通勤距离` |

---

## 11. ★ 舍入语义（跨语言移植最隐蔽的坑）

**桌面端是 Python，移动端是 Dart。两者 `round` 的语义不同，必须复刻。**

### 差异 1：`.5` 的处理方向

| 表达式 | Python | Dart 原生 |
|---|---|---|
| `round(0.5)` / `0.5.round()` | **0** | 1 |
| `round(1.5)` | 2 | 2 |
| `round(2.5)` | **2** | 3 |
| `round(3.5)` | 4 | 4 |
| `round(-0.5)` | **0** | -1 |

Python 是**银行家舍入（half-to-even）**，Dart 是**远离零（half-away-from-zero）**。

### 差异 2：`round(x, n)` 的基准（更隐蔽）

Python 的 `round(x, n)` **不是**「乘 10ⁿ → 舍入 → 除回去」，
而是对 **x 的精确二进制值**做十进制 ROUND_HALF_EVEN。实测差异：

| 表达式 | Python | 朴素法 `pyRound(x*10ⁿ)/10ⁿ` |
|---|---|---|
| `round(0.05, 1)` | **0.1** | 0.0 ✘ |
| `round(2.45, 1)` | **2.5** | 2.4 ✘ |
| `round(1.015, 2)` | **1.01** | 1.02 ✘ |
| `round(0.15, 1)` | **0.1** | 0.2 ✘ |
| `round(100.35, 1)` | **100.3** | 100.4 ✘ |
| `round(5.1235, 3)` | **5.123** | 5.124 ✘ |
| `round(30.12345675, 7)` | **30.1234567** | 30.1234568 ✘ |

原因：这些十进制小数的双精度表示并不精确，如
`0.05` 精确值 ≈ `0.050000000000000002776`（第 2 位 >5 → 进），
`2.45` 精确值 ≈ `2.45000000000000017764`（第 2 位 >5 → 进）。

### 落地方式

移动端实现于 **`lib/core/utils/py_round.dart`**：

| 函数 | 对应 | 用途 |
|---|---|---|
| `pyRound(v)` | Python `round(v)` | 心率/踏频/功率等取整 |
| `pyRoundTo(v, n)` | Python `round(v, n)` | `t`/`dist`/`alt`/`speed`/`lat` 等 |

**实现原理**：从 IEEE 754 位模式取精确有理数（`significand × 2^binExp`），
用 `BigInt` 做十进制定点 ROUND_HALF_EVEN，不经过任何 double 中间运算。

**验证**：`tool/verify_py_round.py` 用 **40180 例**（边界值 + 随机 + `.5` 家族）
与 Python 内置 `round()` 逐值比对，**0 失败**。

### 铁律

> **凡是移植桌面端 `round()` 的地方，一律用 `pyRound` / `pyRoundTo`。**
> 直接用 Dart 的 `.round()` / `.toStringAsFixed()` 一律视为 bug。

用 `toStringAsFixed()` 也是错的 —— 它的舍入规则是 Dart 自己的（half-away），
且同样基于二进制值但仍与 Python 不同。

### 已知的舍入调用点清单（审查用）

审查「口径漂移」时按下表逐个核对：

**桌面端 `core/analysis.py`**
| 行 | 桌面端 | 移动端 |
|---|---|---|
| 59 | `round(z, 1)` / `round(z/total*100, 1)` | `analysis.dart::weightedZoneTimes` → `_round1` |
| 96–97 | `round(b[i])`（区间边界标签） | `zones.dart::hrZones` → `pyRound` |
| 155 | `round(dt, 1)` | `analysis.dart::perKm` → `_round1` |
| 156 | `round(avg_speed, 1)` | 同上 |
| 157 | `round(max(speeds)*3.6, 1)` | 同上 |
| 158 | `round(sum(hrs)/len(hrs))` | `_round0` |
| 159 | `round(max(hrs))` | `_round0` |
| 160 | `round(sum(cads)/len(cads))` | `_round0` |
| 161 | `round(sum(alts)/len(alts), 1)` | `_round1` |
| 191–193 | `round(min/max/avg(temps), 1)` | `tempStats` → `_round1` |
| 207 | `int(round(i*step))`（轨迹抽稀） | `trackPoints` → `pyRound` |
| 300 | `round(max(0, power))`（估算功率） | `estimate_power.dart` → `pyRound` |

**桌面端 `core/training_load.py`**
| 行 | 桌面端 | 移动端 |
|---|---|---|
| 45 | `round(np, 1)` / `round(avg, 1)` | `normalizedPower` → `_round1` |
| 61 | `round(tss, 1)` | `_tssFromPower` → `_round1` |
| 100 | `round(total, 1)`（hrTSS） | `_tssFromHr` → `_round1` |
| 120 | `round(np/ftp, 2)` | `computeActivityTss` → `_round2` |
| 175 | `round(ctl-atl, 1)`（TSB） | `buildPerformanceCurve` → `_round1` |
| 184–185 | `round(ctl,1)` / `round(atl,1)` | 同上 |
| 207 | `round(total, 1)`（近 7 天 TSS） | `recentWeekTss` → `_round1` |

**桌面端 `core/month_agent.py`**
| 行 | 桌面端 | 移动端 |
|---|---|---|
| 271 | `round(avg, 1)` | `month.dart::_safeAvg` + `_round1` |
| 290–297 | `round(..., 1)` / `round(...)` | `monthOverview` |
| 341 | `round(distance_km, 1)` | `monthDistanceTrend` → `_round1` |
| 345–346 | `round(max/min, 1)` | 同上 |
| 359–360 | `round(avg)` / `round(max)` | `monthHrSummary` → `_round0` |
| 372–375 | `round(..., 1)` | `month.dart` |

**桌面端 `core/fit_parser.py`**（逐点字段舍入）
| 字段 | 桌面端 | 移动端 |
|---|---|---|
| `t` | `round(t, 1)` | `parser.dart::_round(t, 1)` |
| `lat` / `lon` | `round(x, 7)` | `_round(x, 7)` |
| `dist_m` | `round(dist, 1)` | `_round(dist, 1)` |
| `speed_ms` | `round(speed, 3)` | `_round(speed, 3)` |
| `hr` / `cad` / `power` | `round(x)` | `_round(x, 0)` |
| `alt_m` / `temp` | `round(x, 1)` | `_round(x, 1)` |

---

## 测试要求

**每个指标必须有单测，且断言值来自桌面端实际输出。**

做法：用 Python 跑桌面端函数得到期望值，写进 Dart 测试。见
`test/stats/analysis_test.dart` —— 每个金标准用例的注释里都标了
「期望值来自桌面端」。

**这样做的价值：**
- 如果移动端实现正确 → 测试通过 → 继承正确性
- 如果将来有人改了一端算法 → 测试失败 → 立刻发现口径漂移
- 常量测试（`group('常量与桌面端一致')`）专门防"手滑改常量"

---

## 修改流程

改任何统计算法前：

1. **先确认桌面端是否也该改** —— 大概率只改一端是错的
2. 若桌面端确实改了 → 两边同步改 + 更新本文件
3. 若桌面端不改 → 不要改移动端
4. 更新本文件的伪码与金标准用例
5. 跑 `dart test test/stats/` 确认全绿

**禁止行为：**
- 为了"让测试通过"而改断言值（这是掩盖问题）
- 引入"更准"的算法但不回改桌面端（会造成两端行为分叉）
