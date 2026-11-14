# FIT 解析适配层

## 背景：`activity_files` 与桌面端 `fitparse` 的模型差异

这是移动端**最容易出错**的地方，务必先读完本节。

### 桌面端（`core/fit_parser.py`）—— 平铺模型

`fitparse` 把每条 `record` 消息解析成一个 dict，所有传感器字段在同一层：

```python
records = [
    {"t": 0.0, "lat": 30.0, "lon": 120.0, "alt_m": 10.0,
     "hr": 120, "cad": 85, "power": 200, "speed_ms": 5.2, "temp": 25.0},
    {"t": 1.0, "lat": 30.001, "lon": 120.001, "alt_m": 10.5,
     "hr": 121, "cad": 86, "power": 205, "speed_ms": 5.3, "temp": 25.0},
    ...
]
```

**一条记录 = 一个时刻的全部数据。**

### `activity_files` —— 分离模型

GPS 点与传感器数据**分成两路**：

```dart
RawActivity(
  points: [
    GeoPoint(latitude: 30.0, longitude: 120.0, elevation: 10.0, time: ...),
    GeoPoint(latitude: 30.001, longitude: 120.001, elevation: 10.5, time: ...),
    ...
  ],
  channels: {
    Channel.heartRate: [Sample(time: ..., value: 120), Sample(time: ..., value: 121), ...],
    Channel.power:     [Sample(time: ..., value: 200), Sample(time: ..., value: 205), ...],
    Channel.cadence:   [Sample(time: ..., value: 85), ...],
    Channel.speed:     [Sample(time: ..., value: 5.2), ...],
    Channel.temperature: [...],
    Channel.distance:  [...],   // ★ 存在！累计距离（米）
  },
  laps: [...],
  summary: ActivitySummary(...),
)
```

**`GeoPoint` 只有位置信息，不含心率/功率/踏频。**

---

## ✅ 已确认的 API 事实（读源码得出，非猜测）

来源：`activity_files` 0.7.8 源码（`C:\Users\zhengyingjun\Downloads\activity_files-0.7.8\`）。

| 问题 | 结论 | 依据 |
|---|---|---|
| `ChannelMapper.snapshot(t)` 是否插值？ | **不插值**，取「最近的 sample + 容差内」，超容差返回 null | `channel_mapper.dart::_ChannelSeries.nearest`：`delta <= toleranceMicros && delta < bestDelta` |
| 默认容差是多少？ | **5 秒**（`maxDelta` 参数） | `ChannelMapper.cursor(channels, maxDelta: Duration(seconds:5))` |
| 累计距离能否拿到？ | **能**，`Channel.distance`（`'distance'`，单位米） | `models.dart:260`；`fit_parser.dart:962` 会填充它 |
| FIT 解析器填充哪些 channel？ | `heartRate` / `cadence` / `power` / `temperature` / `speed` / `distance`，外加 `extraSamples` | `fit_parser.dart:956–969` |
| 解析入口？ | `ActivityParser.parseBytes(bytes, ActivityFileFormat.fit)` | `activity_parser.dart:46` |
| 返回结构？ | `ActivityParseResult{ activity, diagnostics, integrityStats, integrityMode }` | `parse_result.dart:188` |
| `GeoPoint.elevation` 是否已是米？ | **是**（十进制度/米，非 semicircle/缩放值） | `models.dart:291` |
| `Sample.time` / `GeoPoint.time` 时区？ | 构造时强制 `.toUtc()` | `models.dart:282, 367` |
| 有 `local_timestamp`（时区偏移）吗？ | **没有！被丢弃** — 见下节「⚠️ 两个必须自己补的值」 | `fit_parser.dart:836` |
| `session.start_time` 有吗？ | **没有！被丢弃** | `fit_parser.dart:616-644` |
| `ActivitySummary.subSport` 类型？ | **`int?`（FIT 枚举数值）**，桌面端是**字符串** | `models.dart:813` |
| `ActivitySummary.sport` 类型？ | `Sport?`（枚举），桌面端是字符串 | `models.dart:826` |
| `RawActivity.metadata` 在 FIT 下？ | **恒为空 Map**（FIT 解析器从不写入） | `fit_parser.dart` 全文无 `metadata[` |
| `ActivityDeviceMetadata` 有哪些字段？ | `manufacturer` / `model` / `product` / `softwareVersion`（**无 productName**） | `models.dart:919-950` |

**因此适配层可以放心用 `ChannelMapper.cursor`**，它和桌面端「无插值」口径天然一致。
（容差取 `kChannelTolerance = 2s`，比库默认的 5s 更严 —— 见下方决策点。）

---

## ⚠️ 两个必须自己补的值（否则口径必然偏离桌面端）

`activity_files` 的 FIT 解析器**丢弃**了两个桌面端口径依赖的标量。这不是猜测，
是读源码 + 实测双重确认的结论：

### 1) `activity.local_timestamp` —— 决定时区偏移

桌面端 `core/fit_parser.py:160-170`：
```python
for a in activities:                      # global 34 = activity
    lt = a.get("local_timestamp")         # 字段 5
    ts = a.get("timestamp")               # 字段 253
    diff = (lt - ts).total_seconds()
    if abs(diff) <= 14 * 3600:
        utc_offset_s = int(diff)          # 显示用：start_time / month 依赖它
```
**实测 iGPSPORT 文件：`local=12:53:25` / `ts=04:53:25` → 偏移 `+28800s`（东八区）。**
若拿不到，`start_time` 会差 8 小时，`month` 归属也会错。

**为什么库给不了**：`fit_parser.dart:836` 的 `case 34` 只读字段 0（`total_timer_time`），
字段 5 直接忽略；且 `RawActivity.metadata` 在 FIT 路径下始终为空。

### 2) `session.start_time` —— 决定活动起点

桌面端 `core/fit_parser.py:149-158`：
```python
if session and session.get("start_time") is not None:
    start_dt = session["start_time"]          # 字段 2
elif records:
    start_dt = records[0].get("timestamp")
```
**实测：`session.start_time` 与首条 record 常差 1-2 秒**（例：
`2024-10-01 02:25:12` vs `02:25:10`），直接用首条 record 会让全部 `t` 整体偏移。

**为什么库给不了**：`fit_parser.dart:616-644` 构建 `ActivitySummary` 时不含 start_time。

### 解决方案：`lib/core/fit/fit_supplement.dart`

一个**只读、最小化**的 FIT 扫描器，从原始字节抽出这两个值：

```dart
final supp = readFitSupplement(bytes);
supp.utcOffsetSeconds;    // → 28800（东八区）
supp.sessionStartTime;    // → 2026-07-05 08:33:49Z（UTC）
```

**验证方式**：`mobile/tool/verify_fit_supplement.py`（逐行等价移植）
拿 10 个真实 FIT 文件比对 fitparse 金标准 —— **9/10 完全一致**。

**第 10 个（`example.fit`，2015 年遗留文件，protocol v1.6）** 是文件本身
**没有 session 数据记录**（只有定义），且此时 `session.start_time == 首条 record 时间`，
所以回退到首点后结果**依然正确**。属于可接受的降级。

**踩过的坑（已在代码中修正，勿回退）**：
- developer field 定义的每项是 **3 字节** `(field_number, size, developer_index)`；
  最初只跳过 2 字节 → 流在含 developer 字段的文件上失步（`ds` 从 52 变 76）。
  实测文件 `ride-0-2026-08-01-14-47-20.fit` 的 lap 定义有 13 个 developer 字段（共 52 字节）。
- 压缩时间戳帧（`header & 0x80`）只用 **1 字节** 存时间戳，其余字段沿用定义。
- `isDefinition` / `hasDevData` 必须 gate 在 `!isCompressed` 上（与库一致）。

---

## 适配层要做的事

**把分离模型还原成桌面端的平铺语义**，让上层的统计算法（`lib/core/stats/`）
可以像桌面端一样工作。

```
activity_files 输出 (points + channels)
              ↓
        【适配层 join】
              ↓
List<ActivityRecord>（平铺，字段名同桌面端 records）
              ↓
        统计算法直接使用
```

实现：`lib/core/fit/parser.dart::parseActivityBytes()`

### 关键决策点

#### 1. 时间戳对齐策略

`points` 和 `channels` 的时间戳不一定完全一致。**策略：**

- 以 `points` 为时间轴主干（若无 GPS，退化为所有 channel 时间戳的并集）
- 对每个时间点，从各 channel 取**最近的** `Sample`（`ChannelMapper` 自带）
- **不插值**，取不到就留 null
- 容差 `kChannelTolerance = 2s`（比库默认 5s 严，避免把停车期间的数据错接上）

#### 2. 记录频率归一

若 `points` 是 1 Hz、某 channel 是 0.5 Hz，join 后会出现交替的 null。
统计层已处理 null（`continue`）。**不要**为了"填满"而插值。

#### 3. 距离字段

`Channel.distance` 存在，**优先用 FIT 自带的累计距离**；
缺失时按桌面端口径用**速度积分补全**（`parser.dart` 里已实现，对应
`fit_parser.py:219–227`）。

#### 4. 时间基准

桌面端：`t = max(0.0, ts - start_ts)`（相对活动开始的秒数）。
移动端同样：起点取 `supplement.sessionStartTime ?? 时间轴首点`，
对应桌面端「`session.start_time` 优先，否则首条 record」。

#### 4b. sport / sub_sport 名称

| | 桌面端（fitparse） | 移动端（activity_files） | 适配层 |
|---|---|---|---|
| `sport` | `'cycling'` 字符串 | `Sport.cycling` 枚举 | `.name` → 字符串 |
| `sub_sport` | `'road'` 字符串 | `7` 整型 | `fitSubSportName(7)` → `'road'` |

数值 → 名称表在 `lib/core/fit/fit_enums.dart`，**用桌面端 venv 的
`fitparse.profile` 直接导出**（61 项 sub_sport + 全线 sport），保证逐字一致。
转换后即可套用桌面端 `SUB_SPORT_CN` 中文表。

⚠️ 实测 Magene C606 Pro 的 `sub_sport = 252` 是**厂商私有值**，
不在 FIT 官方枚举内 → `fitSubSportName` 返回 null → 上层退化为空串，
与桌面端 `sub_sport = sget("sub_sport") or ""` 行为一致。

#### 5. 汇总字段 —— ★ 最容易错的地方

`ActivitySummary` 的字段**优先使用**（桌面端就是优先信 session 值），
仅在缺失时才从 records 自算。详见 `lib/core/stats/summarize.dart` 顶部表格。

**实测的一个关键事实：`timer_s == moving_s`**（iGPSPORT 文件两者都是 4312.0），
因为桌面端把 `total_moving_time` 也当作 timer 的兜底来源。
而 `moving_s` 本身**没有自算兜底** —— FIT 没有就是 null。

---

## 桌面端参考输出（用于逐字段比对）

用真实文件跑 `core/fit_parser.py` 得到，作为移动端的金标准。

### A. iGPSPORT BSC200（无心率、无功率）

文件：`码表fit数据\igp\bsc200\ride-0-2026-07-05-16-33-49.fit`

| 字段 | 值 |
|---|---|
| `file_hash` | `75f6e8e0e83b52982cbf37227b1f30d36e7740f3` |
| `start_time` | `2026-07-05 16:33:49` |
| `start_ts` | `1783211629` |
| `device` | `iGPSPORT` |
| `sport` / `sub_sport` | `cycling` / `road`（公路骑行） |
| `record_count` | **4323** |
| `total_distance_m` | `20536.2` |
| `timer_s` | `4312.0` |
| `elapsed_s` | `4743.0` |
| `moving_s` | `4312.0` |
| `avg_speed_ms` | `4.762` |
| `max_speed_ms` | `7.986` |
| `avg_hr` | `None` |
| `avg_cad` / `max_cad` | `58` / `82` |
| `ascent_m` / `descent_m` | `31.0` / `33.0` |
| `avg_alt_m` / `max_alt_m` / `min_alt_m` | `68.2` / `76.0` / `64.0` |
| `avg_temp` / `max_temp` | `27.0` / `29.0` |
| `lat` / `lon` | `41.7903798` / `123.4285802` |

首条 record：
```python
{'t': 0.0, 'lat': 41.7903884, 'lon': 123.4286255, 'dist_m': 0.0,
 'speed_ms': 3.687, 'hr': None, 'cad': 29, 'alt_m': 76.0, 'temp': 27.0, 'power': None}
```
末条 record：
```python
{'t': 4743.0, 'lat': 41.7898518, 'lon': 123.4278048, 'dist_m': 20536.2,
 'speed_ms': 2.555, 'hr': None, 'cad': 32, 'alt_m': 67.0, 'temp': 27.0, 'power': None}
```

**注意**：末条 `t = 4743`（等于 `elapsed_s`），不是 `timer_s` —— 因为逐条记录
覆盖整个 elapsed 区间（含停车）。

### B. Magene C606 Pro（有心率、无踏频）

文件：`码表fit数据\迈金\MAGENE_C606Pro_2026-08-14_181042_1283238.fit`

| 字段 | 值 |
|---|---|
| `file_hash` | `78634d03b01ded5539f2b768aec62a1600988456` |
| `start_time` | `2026-08-14 18:10:43` |
| `start_ts` | `1786673442` |
| `device` | `Magene（迈金）` |
| `sport` / `sub_sport` | `cycling` / `252`（未翻译，厂商私有值） |
| `record_count` | **4663** |
| `total_distance_m` | `37403.9` |
| `timer_s` | `4661.0` |
| `elapsed_s` | `7737.0` |
| `moving_s` | `4661.0` |
| `avg_speed_ms` | `8.024` |
| `max_speed_ms` | `12.705` |
| `avg_hr` / `max_hr` | `154` / `187` |
| `avg_cad` / `max_cad` | `None` |
| `ascent_m` / `descent_m` | `23.0` / `28.0` |
| `avg_alt_m` / `max_alt_m` | `101.8` / `106.2` |
| `avg_temp` / `max_temp` | `27.0` / `29.0` |
| `lat` / `lon` | `41.7533499` / `123.2346` |

首条 record 的 `t = 10.0`（不是 0）—— 说明 `start_time` 来自 session，
而首条 record 时间比 session 起点晚 10 秒。
**这正是 `fit_supplement.dart` 要解决的问题**：用 `session.start_time` 当起点，
`t` 就与桌面端一致；若用首点，全部 `t` 会整体偏移 10 秒。

---

## 落地清单

- [x] 读到 `activity_files` 源码，确认 `ChannelMapper` 不插值、有 `Channel.distance`
- [x] 实现 `lib/core/fit/parser.dart`：`RawActivity` → `List<ActivityRecord>`
- [x] 实现 `lib/core/stats/summarize.dart`：汇总字段（会话值优先）
- [x] 生成桌面端参考输出（上面 A/B 两例）
- [x] 确认 `RawActivity.metadata` **不含** `local_timestamp` → 自建 `fit_supplement.dart`
- [x] 确认 `ActivitySummary` **不含** `start_time`，`subSport` 是 `int?` → 自建映射表
- [x] 用 10 个真实 FIT 文件验证 `fit_supplement` 算法（9/10 一致，1 例可安全降级）
- [ ] **用移动端跑同一文件，与上面 A/B 逐字段比对**
- [ ] 比对通过后，把金标准值写进 `test/fit/parser_test.dart`

**在对齐验证通过前，不要进入 UI 开发** —— 数据不对，UI 再漂亮也没意义。

### 比对方法（建议）

在移动端写一个临时脚本（或 Dart 测试）打印同名字段，人工对照上表：

```dart
final bytes = File(fitPath).readAsBytesSync();
final parsed = parseActivityBytes(Uint8List.fromList(bytes),
    fileName: 'ride-0-2026-07-05-16-33-49.fit');
final act = parsed.toActivity(summarize: buildActivitySummary);
print('hash=${parsed.fileHash}');
print('records=${parsed.records.length}');
print('dist=${act.totalDistanceM} timer=${act.timerS} moving=${act.movingS}');
print('avgSpd=${act.avgSpeedMs} maxSpd=${act.maxSpeedMs}');
print('cad=${act.avgCad}/${act.maxCad} ascent=${act.ascentM}/${act.descentM}');
print('alt=${act.avgAltM}/${act.maxAltM}/${act.minAltM}');
print('temp=${act.avgTemp}/${act.maxTemp}');
print('first=${parsed.records.first}');
print('last=${parsed.records.last}');
```

**判读要点：**
- `record_count` 若与桌面端不同 → 说明时间轴主干选错（points vs 并集）
- `first.t` 若为 0 而桌面端为 10 → 起点取值逻辑不同（见 B 例）
- `ascent/descent` 差异 → 滞回算法或海拔采样频率不同
- `timer/moving` 差异 → `ActivitySummary` 字段名对不上
