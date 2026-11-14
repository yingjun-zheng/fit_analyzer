# 移动端规划（Flutter）—— 手机上的 fit_analyzer

> 状态：**规划阶段，未动手**（用户 2026-09-20 指示"先规划，不要着急动手"）
>
> **⚠️ 本文档为第 2 版，已推翻第 1 版。**
> 第 1 版把手机端定位成"轻量看数据，重的留桌面"，并花大量篇幅设计"两端数据同步"。
> **方向错误**：目标用户**只有手机、没有电脑**，不存在"另一端"。同步、口径对齐都是伪问题。
> 正确方向：**把 fit_analyzer 的聚合分析能力完整搬到手机上。**

---

## 一、一句话定位

**手机上的 fit_analyzer —— 骑行者的唯一分析设备。**

- 目标用户：**只有手机、没有电脑**的骑行爱好者
- 核心价值：**多平台数据聚合 + 完整分析**，不依赖任何桌面设备
- 不是"桌面端的简化版"，而是**独立完整的产品**

---

## 二、痛点与设计前提

### 2.1 真实痛点

```
很多骑行爱好者没有电脑
        ↓
但他们的数据散落在 iGPSPORT / 佳明 / 行者 / 黑鸟 / 迈金 … 各平台
        ↓
每个平台只能看自己那份，无法统一分析
        ↓
他们需要 fit_analyzer 那种「聚合 + 分析」能力
        ↓
但 fit_analyzer 是桌面程序，他们用不了
```

### 2.2 由此推出的设计前提

| 前提 | 说明 |
|---|---|
| **手机是唯一设备** | 所有能力必须在手机端闭环，不能有任何"去电脑上看"的降级 |
| **没有"另一端"** | 不需要双端同步、不需要口径对齐（只有一套实现） |
| **必须能离线** | 骑行场景常在户外，网络不稳定 |
| **必须好用** | 用户没有备选方案，不好用就是没有 |

### 2.3 由此推翻的两个伪问题

| 第 1 版的关注点 | 为什么是伪问题 |
|---|---|
| 两端口径对齐 | 只有手机端一套实现，对齐无从谈起 |
| 双端数据同步 | 用户没有电脑，没有第二端 |

**唯一保留的相关思考**：如果将来要做桌面端，那是"给已有手机用户的可选补充"，不是必需。

---

## 三、功能范围（对齐 fit_analyzer 的完整能力）

### 3.1 ✅ 核心能力（必须做，这是产品价值所在）

| # | 功能 | 说明 | 桌面端对应 |
|---|---|---|---|
| 1 | **多平台数据聚合** ⭐ | iGPSPORT / 佳明 / 行者 / 黑鸟 / 迈金 / Wahoo / Intervals.icu… 的登录 + 拉取活动 | 参考项目 `api/*Api.kt` + `core/garmin_sync.py` |
| 2 | **统一活动库** | 所有平台数据汇入一个本地库，去重、统一格式 | `db.py` |
| 3 | **活动列表** | 全部/按月/按年，筛选排序（距离/时长/爬升/类型） | `db.list_activities` |
| 4 | **月度统计** | 总距离/时长/爬升/次数/卡路里/均速，环比上月 | `month_agent._month_overview` |
| 5 | **年度统计** | 年度累计、月度分布、逐年对比 | `month_agent` 扩展 |
| 6 | **趋势分析** | 近 6/12/24 个月多指标折线趋势 | 新增 |
| 7 | **个人纪录（PR）** | 最长距离、最大爬升、最快均速、最大功率… | `fitness.py` |
| 8 | **单次深度分析** ⭐ | 速度/海拔/心率/功率/踏频**多图联动** + 区间分布 + 按公里分段 | `analysis.py` |
| 9 | **圈（lap）分析** | 分段表格 + 圈间对比 | `fit_parser` laps |
| 10 | **训练负荷** | TSS / CTL / ATL / TSB（需 FTP） | `training_load.py` |
| 11 | **区间统计** | 功率区间 / 心率区间 / 速度区间 / 踏频区间，带时间权重 | `analysis._weighted_zone_times` |
| 12 | **AI 分析** ⭐ | 自然语言问「本月骑了多少」「上周比前周强度如何」；AI 解读单次骑行 | `ai_analysis.py` + `month_agent` + `nl_query.py` |
| 13 | **通勤打标** | 标记通勤/训练，统计分开算 | `commute` 字段（P3 已有） |
| 14 | **多车/装备管理** | 车辆、里程累计、装备寿命提醒 | `gear.py` |
| 15 | **数据导出** | 导出 FIT/GPX/CSV | `gpx_export.py` / `excel_export.py` |

### 3.2 🟡 可选（看工作量）

| 功能 | 说明 |
|---|---|
| 轨迹地图 | 只读展示，注意中国测绘合规 |
| 骑行路段对比 | 同一条路的多次骑行对比 |
| 分享图 | 生成骑行摘要图片（参考项目有透明贴纸方案） |
| 周报/月报 | 自动生成的图文报告 |
| 天气关联 | 骑行时的天气（`weather.py`） |

### 3.3 ❌ 明确不做

| 功能 | 原因 |
|---|---|
| **路书制作 / 路径规划** | 需地图全屏 + 拖拽打点 + 海拔剖面，手机体验差；用户已确认不做 |
| Excel 报表导出 | 手机场景不需要 Excel |
| 自动上传到其他平台 | 第一版不做（协议多、成功率不稳），架构预留 |

---

## 四、与 fit_analyzer 的关系（重新定义）

**不是"结合"，是"移植 + 能力对齐"。**

| 层面 | 关系 |
|---|---|
| **能力** | 手机端**完整对齐** fit_analyzer 的核心分析能力 |
| **定位** | 手机端是**独立产品**，不是桌面端的附属 |
| **代码** | 不共享（Python → Dart 无法直接复用），**只对齐能力与口径** |
| **口径** | 手机端**照抄** fit_analyzer 的算法（因为它是对的），保证"同一个 App 的逻辑" |
| **数据** | 各自独立存储，无同步需求 |

**为什么还要"照抄口径"？**
不是因为要对齐另一端，而是因为 **fit_analyzer 的算法是经过 13 个版本打磨的正确实现**。重写时以它为基准，能避免重新踩坑（比如爬升的滞回参考点法、区间的时间加权）。这是**继承正确性**，不是**对齐两端**。

**长期形态：**

```
        手机端（Flutter）—— 主产品，覆盖 95% 用户
   ┌──────────────────────────────────────────┐
   │ 多平台聚合 · 统一活动库 · 统计分析        │
   │ 单次深度分析 · 训练负荷 · AI 分析         │
   └──────────────────────────────────────────┘

        桌面端（PySide6）—— 现存产品，服务有电脑的用户
   ┌──────────────────────────────────────────┐
   │ 同上能力 + 路书 + Excel + 批量导入        │
   └──────────────────────────────────────────┘
```

---

## 五、技术选型

### 5.1 已确定：Flutter

| 项 | 值 |
|---|---|
| Flutter 版本 | **3.47.5 stable**（Dart 3.13.4） |
| 下载源 | `https://storage.flutter-io.cn`（国内镜像，已实测可用） |
| 本机现状 | ❌ 未安装 Flutter SDK；✅ 已有 `D:\Android\Sdk`（platform-36 + build-tools 36.1.0）、Java 17.0.19、Gradle 9.5.1 |
| 待补 | Flutter SDK（解压后约 1.5 GB） |

### 5.2 关键库

| 用途 | 库 | 理由 |
|---|---|---|
| 路由 | `go_router` | 官方推荐 |
| 状态管理 | `riverpod` | 编译期安全，测试友好 |
| 本地数据库 | **`drift`**（SQLite ORM） | 类型安全 + 迁移能力；表结构对齐 `db.py` |
| HTTP | `dio` | 拦截器（token 刷新、重试、Cookie） |
| 图表 | **`fl_chart`** | 柱状/折线/曲线全支持 |
| **FIT/GPX/TCX 解析** | **`activity_files` ^0.7.8** | ⭐ 纯 Dart、零原生依赖、五格式互转、容错、isolate |
| FIT 底层补充 | `fit_sdk` ^0.3.0 | 备选，Garmin FIT SDK 的 Dart 移植 |
| 文件选择 | `file_picker` | 选 FIT/GPX |
| 安全存储 | `flutter_secure_storage` | token 加密存（Keystore/Keychain） |
| 地图（可选） | `flutter_map` | 免 Key（OSM）；注意测绘合规 |
| 后台任务（可选） | `workmanager` | 定时拉取新活动 |
| 分享图（可选） | `screenshot` + `share_plus` | 生成摘要图 |

---

## 六、架构设计

### 6.1 分层

```
lib/
├── main.dart
├── app.dart
├── core/
│   ├── models/                  # Activity / Lap / Record / MonthStats
│   ├── db/                      # drift 数据库 + DAO + 迁移
│   ├── fit/                     # ★ 口径适配层（activity_files → 桌面端语义）
│   ├── stats/                   # ★ 统计口径（照抄 fit_analyzer 算法）
│   │   ├── summary.dart         #   爬升、移动时间、均速…
│   │   ├── zones.dart           #   区间时间加权
│   │   ├── per_km.dart          #   按公里分桶
│   │   ├── month.dart           #   月度/年度统计
│   │   └── training_load.dart   #   TSS/CTL/ATL/TSB
│   └── utils/
├── data/
│   ├── sources/                 # ★ 多平台数据源（产品核心价值）
│   │   ├── source.dart          #   抽象接口
│   │   ├── igpsport.dart
│   │   ├── garmin.dart
│   │   ├── xingzhe.dart
│   │   ├── blackbird.dart
│   │   ├── magene.dart
│   │   ├── wahoo.dart
│   │   ├── intervals_icu.dart
│   │   └── local_file.dart
│   └── repositories/
├── features/
│   ├── home/                    # 首页（概览卡 + 最近活动）
│   ├── activities/              # 活动列表 + 筛选
│   ├── detail/                  # 单次深度分析（多图联动/圈/区间）
│   ├── stats/                   # 月度 / 年度 / 趋势 / PR
│   ├── ai/                      # AI 问答
│   ├── gear/                    # 车辆/装备
│   ├── import/                  # 平台登录与拉取
│   └── settings/                # 设置（FTP/体重/单位）
└── widgets/
```

### 6.2 数据流

```
多平台适配器 → 拉取 FIT → activity_files 解析 → 口径适配层 → drift 入库
                                                                   ↓
                                                          统计层（stats/）
                                                                   ↓
                                                          各页面 UI
                                                          ＋ AI 层（读统计结果）
```

**关键：统计层是纯函数**（输入 activity 列表 → 输出统计结果），与 UI 解耦，便于单测。

---

## 七、★ FIT 解析：无需自研

> 第 1 版曾判断"Dart 无 FIT 解析库、需自研 700–900 行"，**该判断是错的**，已更正。

### 7.1 主选：`activity_files` 0.7.8

| 项 | 值 |
|---|---|
| 更新时间 | **2026-09-19**（调研前一天刚发版，极活跃） |
| 维护者 | `eikedreier.xyz`（pub.dev **verified publisher**） |
| 许可证 | **BSD 3-Clause** |
| 依赖 | `async` / `args` / `collection` / `xml` / `csv` —— **纯 Dart，零原生依赖** |
| 要求 | Dart SDK `^3.9.0`（Flutter 3.47.5 自带 Dart 3.13.4 ✅） |

**能力：** FIT/GPX/TCX/GeoJSON/CSV 五格式解析+编辑+校验+转换；GPS 点、传感器通道（心率/功率/踏频）、session 汇总、lap 分段、设备元数据；畸形文件不抛异常（返回带 code 的 diagnostics）；`useIsolate` 解析不卡 UI。

### 7.2 ⚠️ 数据模型与桌面端不同（关键差异）

| 维度 | 桌面端 `fit_parser.py` | `activity_files` |
|---|---|---|
| **数据组织** | **平铺**：每条 record 含 lat/lon/alt/hr/power/cad/speed | **分离**：`points`（只有纬度/经度/海拔/时间）+ `channels`（心率/功率/踏频各成一路，每点 `Sample(time, value)`） |
| **取值** | `record["hr"]` 直接读 | `ChannelMapper.cursor(channels).snapshot(point.time)` 按时间查找 |
| **字段命名** | snake_case | camelCase |

**→ 必须按时间戳 join 才能还原成桌面端 record 语义。这是适配层（`core/fit/`）的核心工作。**

备选：`fit_sdk` 0.3.0（Garmin FIT SDK 的 Dart 移植）。

---

## 八、★ 统计口径：照抄 fit_analyzer 的算法

> **不是"对齐两端"，是"继承正确实现"。** fit_analyzer 的算法经 13 个版本打磨，重写时以它为准，避免重新踩坑。

### 8.1 必须自己算（不能信 FIT 文件自带值）

| # | 指标 | fit_analyzer 算法 | 为什么不能用文件值 |
|---|---|---|---|
| 1 | **爬升 / 下降** | `accumulate_ascent_descent(eles, threshold=1.0)`：**滞回参考点法** —— 维护参考海拔，累计变化达 1.0 m 才计入并把参考点移到当前值 | 朴素「正增量全加」会大幅灌水；各厂商 `total_ascent` 算法也不同 |
| 2 | **移动时间** | `moving_time()`：speed > 0.5 m/s 视为移动，累加相邻时间差 | 与 FIT 的 `total_moving_time`、用 events 算的都不同 |
| 3 | **里程加权平均速度** | `Σ(均速×距离)/Σ距离` | 与算术平均是两个数字，UI 必须标注用哪个 |
| 4 | **区间时间** | `_weighted_zone_times`：按相邻记录时间差加权，`dt = min(下一条t − 当前t, 30.0)`，dt=0 取 1.0 | 简单计数在记录间隔不均时误差大 |
| 5 | **按公里分桶** | `per_km()`：按 `int(dist // 1000)` 分桶，桶内用首末距离/时间算均速 | 逻辑较绕，必须照搬 |
| 6 | **曲线抽稀** | `downsample_series(max_points=600)` / `track_points(max_points=2000)`：等间隔索引采样 | 采样点数影响曲线形状 |
| 7 | **估算功率** | `estimate_power()`：物理模型 P = (F_roll + F_air + F_gravity + F_accel) × v，5 点平滑，clamp ±1.5 m/s² | 无功率计时用，需标 `power_estimated=True` |
| 8 | **TSS / CTL / ATL / TSB** | `training_load.py`：需 FTP，NP = 30s 滑窗 4 次方均值开 4 次方 | 训练负荷核心指标 |

**⚠️ `ALTITUDE_NOISE_THRESHOLD_M = 1.0` 等常量必须原样照抄。**

### 8.2 月度统计口径（照抄 `_month_overview`）

| 指标 | 口径 |
|---|---|
| `count` | 该月活动条数 |
| `distance_km` | `Σ total_distance_m / 1000`，1 位小数 |
| `hours` | `Σ timer_s / 3600`，1 位小数 |
| `ascent_m` | `Σ ascent_m`，取整 |
| `calories` | `Σ calories`，取整 |
| `avg_speed_kmh` | **各活动均速的算术平均**（仅含有均速的活动） |
| `weighted_avg_speed_kmh` | `Σ(均速 × 距离) / Σ距离` —— **按里程加权** |
| `commute` | `commute` 标记拆出的通勤次数/距离 |
| `training_distance_km` | `总距离 − 通勤距离` |

**UI 注意**：「平均速度」有歧义，必须明确标注用的是哪个（建议主显加权平均，更符合直觉）。

### 8.3 契约文档 + 测试

- **契约文档** `docs/metrics-contract.md`：每条指标写明算法、常量、**伪码**、fit_analyzer 实现位置、移动端实现位置
- **单元测试**：每个统计算法都要有测试，输入固定的 records，断言输出（可用 fit_analyzer 的输出作为期望值 —— **这是继承正确性的具体手段**）
- **对账**：用真实 FIT 文件跑，与 fit_analyzer 输出比对一次，确认口径一致（一次性验证，不是持续的"两端同步"）

---

## 九、多平台数据源（产品核心价值）

> 这是"聚合"的关键 —— 单一平台只能看自己那份数据，聚合才有价值。

### 9.1 优先级

| 优先级 | 平台 | 理由 | 参考实现 |
|---|---|---|---|
| 1 | **本地文件导入** | 兜底，必定可用 | `file_picker` |
| 2 | **iGPSPORT** | 国内骑行主流码表 | `api/IgpsportApi.kt`（310 行） |
| 3 | **佳明 Garmin** | 用户量最大 | `core/garmin_sync.py` + `api/GarminApi.kt` |
| 4 | **行者** | 国内主流 App | `api/XingzheApi.kt`（192 行） |
| 5 | **黑鸟单车** | 国内主流 | `api/BlackbirdApi.kt`（830 行） |
| 6 | **迈金 Magene** | 国内主流 | `api/MageneApi.kt`（328 行） |
| 7 | **Wahoo** | 国际主流 | `api/WahooApi.kt` |
| 8 | **Intervals.icu** | 协议最简，可快速验证 | `api/IntervalsIcuApi.kt`（102 行） |
| 9+ | 高驰 / 百锐腾 / 捷安特 / 咕咚 / Keep / Zepp / Komoot / Suunto | 按需 | 参考项目各有实现 |

### 9.2 各平台的坑（来自参考项目实战记录）

| 平台 | 坑 |
|---|---|
| **佳明** | **MFA 不支持**（需先在佳明 App 关两步验证）；**429 风控触发 24h 冷却**；用 `connectapi.garmin.com` 直连可绕 Cloudflare（比 WebView 快 5–10×） |
| **iGPSPORT** | 登录 `login.passport.igpsport.cn`；活动列表需 `pageNo/pageSize` 翻页（无服务端 offset，要拉完丢弃）；时间字段有 23 种候选名；下载走 `getDownloadUrl` |
| **行者** | 用 **Cookie `sessionid=`** 鉴权（Bearer 无效）；GPX 下载 URL **必须带尾部斜杠**，否则 Django 401 |
| **迈金** | 登录用 **MD5(password)**；token 要验 `exp`；下载有两条路（七牛直链 WGS84 / fit_content GCJ-02） |
| **黑鸟** | 坐标为 **GCJ-02**，需转 WGS84；无 FIT 时从 `track` 字符串自建 FIT |
| **Wahoo** | **10 令牌上限**（需淘汰旧 token）；iGPSPORT→Wahoo 成功率仅 50–80% |

---

## 十、AI 分析（做）

| 项 | 方案 |
|---|---|
| 能力 | ① 自然语言问答（「本月骑了多少」「上周强度如何」）② 单次骑行 AI 解读 ③ 训练建议 |
| 实现 | 复用 `fit_analyzer` 的 `ai_analysis.py` / `month_agent.py` / `nl_query.py` 的**思路**，Dart 重写 |
| 模型接入 | 用户自填 `base_url` / `api_key` / `model`（同桌面端设计），存 `flutter_secure_storage` |
| 上下文构造 | **不把原始 records 发给模型**（太大），而是先算好统计摘要，把摘要给模型 —— 桌面端就是这么做的（`build_full_digest`） |
| 成本控制 | 用户自己的 key，App 不承担成本 |
| 离线 | AI 需联网；离线时功能隐藏或提示 |

---

## 十一、分阶段路线

| 阶段 | 内容 | 产出 |
|---|---|---|
| **P0** | 装 Flutter SDK + 项目骨架 | 可运行的空 App |
| **P1** | FIT 解析适配层 + 统计算法（照抄口径）+ 单测 | 能把 FIT 解析成正确指标 |
| **P2** | drift 数据库 + 本地文件导入 | 能导入并持久化 |
| **P3** | 活动列表 + 单次深度分析（多图/圈/区间） | ⭐ 核心价值页面 |
| **P4** | 月度 / 年度 / 趋势统计 | ⭐ 聚合价值页面 |
| **P5** | 多平台数据源：本地 → iGPSPORT → 佳明 → 行者 | ⭐ **聚合能力** |
| **P6** | 训练负荷（TSS/CTL/ATL/TSB）+ PR + 通勤打标 | 完整分析能力 |
| **P7** | AI 分析 | 智能问答 |
| **P8** | 装备管理 / 导出 / 地图（可选） | 增强 |

**顺序原则：P1 是地基（算法正确性），P5 是产品差异化（聚合）。两者的优先级高于 UI 美化。**

---

## 十二、与 fit_analyzer 代码资产的关系

| fit_analyzer 文件 | 移动端怎么用 |
|---|---|
| `core/fit_parser.py` | 理解 FIT 字段语义 + 时区处理；`activity_files` 负责二进制解析 |
| `core/analysis.py` | **算法照抄**（爬升/区间/分桶/抽稀/移动时间/估算功率） |
| `core/training_load.py` | **算法照抄**（TSS/CTL/ATL/TSB） |
| `core/month_agent.py` | **统计口径照抄** + AI 工具调用思路 |
| `core/db.py` | **表结构照抄**（activities/laps/records/gear） |
| `core/gear.py` | 装备管理逻辑 |
| `core/ai_analysis.py` / `nl_query.py` | AI 问答思路 |
| `core/gpx_export.py` / `excel_export.py` | 导出（Excel 不做） |
| `core/garmin_sync.py` | 佳明数据源参考 |
| `gui/` | 无需参考（Flutter 完全不同） |

---

## 十三、参考项目可借鉴（`sports-data-sync-multiplatform-main`）

| 借鉴什么 | 来源 |
|---|---|
| 各平台登录/拉取协议 | `api/*Api.kt`（19+ 平台） |
| 佳明移动 SSO / DI Token / OAuth1 / 429 处理 | `api/GarminApi.kt`（1661 行） |
| GCJ-02 → WGS84 迭代转换 | `api/BlackbirdApi.kt` / `util/FitGcj02Fixer.kt` |
| 速度卡尔曼滤波、爬升平滑、功率校准 | `api/BlackbirdApi.kt` |
| FIT 二进制结构（写解析器的教材） | `api/FitBuilder.kt`（152 行） |
| 平台能力矩阵（可行性路线图） | `model/Activity.kt` 的 `UploadSupport` |

**⚠️ 许可证**：该仓库 README 标注 MIT 但**根目录无 LICENSE 文件**，`THANKS.md` 列了 6 个上游算法来源 → **只借鉴协议逻辑，代码自己重写**。

---

## 十四、已探明的环境事实

| 项 | 状态 |
|---|---|
| Flutter SDK | ❌ 未安装，需下载 `flutter_windows_3.47.5-stable.zip` |
| 国内镜像 | ✅ `storage.flutter-io.cn` 可用（实测返回 3.47.5） |
| Android SDK | ✅ `D:\Android\Sdk`，platform-36 + build-tools 36.1.0 + 37.0.0 |
| Java | ✅ 17.0.19 |
| Gradle | ✅ 9.5.1（系统级；Flutter 项目自带 wrapper） |
| 磁盘 | ✅ C: 剩 341 GB / D: 剩 269 GB |
| `cmdline-tools` | ⚠️ 为空，接受 license 时可能需补装 |

---

## 十五、第 1 版错在哪（记录，避免重犯）

| 第 1 版的判断 | 错在哪 |
|---|---|
| "手机端做轻量看数据，重的留桌面" | ❌ 用户没有桌面端，留不了 |
| "两端数据同步" | ❌ 只有一端，没有同步对象 |
| "两端口径对齐" | ❌ 只有一套实现 |
| "AI 不做" | ❌ 用户明确要做 |
| "深度训练分析不做" | ❌ 用户明确要做 |
| "手机是数据入口，桌面是分析引擎" | ❌ 手机必须是完整的分析设备 |

**教训：先问清"用户是谁、有什么设备、痛点是什么"，再谈技术方案。** 第 1 版在没搞清楚用户画像的前提下就设计了架构，导致整个方向偏掉。

---

## 十六、下一步

1. **确认本版规划**（功能范围、优先级）
2. 确认后 → 安装 Flutter SDK → 从 P1 开始（**FIT 解析适配层 + 统计算法照抄**）

**优先级建议：先把 P1+P2+P3（解析/存储/单次分析）做扎实，这是产品的地基；再做 P5（多平台聚合），这是差异化。**
