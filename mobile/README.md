# fit_analyzer mobile

手机上的 fit_analyzer —— **骑行数据聚合分析器**。

目标用户是**只有手机、没有电脑**的骑行爱好者。他们的数据散落在
iGPSPORT / 佳明 / 行者 / 黑鸟 / 迈金 等各平台，每个平台只能看自己那份，
无法统一分析。本项目把 fit_analyzer 的聚合分析能力搬到手机上。

**不是桌面端的简化版，是独立完整的产品。**

---

## 与 fit_analyzer 桌面端的关系

| 层面 | 关系 |
|---|---|
| 能力 | 完整对齐桌面端的核心分析能力 |
| 定位 | 独立产品，不依赖桌面端 |
| 代码 | 不共享（PySide6 vs Flutter） |
| **算法口径** | **照抄**桌面端实现 —— 继承其经 13 个版本打磨的正确性 |

**为什么照抄口径？** 不是因为要"对齐另一端"（只有一端），而是因为
桌面端算法已踩过坑、是正确的。重写时以它为准，避免重新踩坑。

`docs/metrics-contract.md` 是口径的单一真相源。

---

## 功能范围

### 核心（产品价值）

- **多平台数据聚合** ⭐ —— iGPSPORT / 佳明 / 行者 / 黑鸟 / 迈金 / Wahoo / Intervals.icu
- **统一活动库** —— 去重、统一格式、本地 SQLite、离线可用
- **单次深度分析** ⭐ —— 速度/海拔/心率/功率/踏频多图联动 + 区间分布 + 按公里分段
- **统计与趋势** —— 月度 / 年度 / 趋势 / 个人纪录
- **训练负荷** —— TSS / CTL / ATL / TSB
- **AI 分析** ⭐ —— 自然语言问答 + 单次解读

### 不做

- 路书制作 / 路径规划（手机体验差）
- Excel 报表导出

---

## 目录结构

```
lib/
├── core/
│   ├── models/          # Activity / ActivityRecord
│   ├── db/              # drift 数据库
│   ├── fit/             # ★ FIT 解析适配层（详见该目录 README）
│   └── stats/           # ★ 统计口径（照抄桌面端）
│       ├── metrics.dart        # 常量（必须与桌面端一致）
│       ├── analysis.dart       # 爬升/区间/分桶/抽稀
│       ├── training_load.dart  # NP/TSS/CTL/ATL/TSB
│       └── month.dart          # 月度/年度/趋势/PR
├── data/
│   └── sources/         # 多平台数据源适配器
├── features/            # 页面
└── widgets/             # 共享组件

docs/
└── metrics-contract.md  # ★ 统计口径契约（单一真相源）

test/stats/
└── analysis_test.dart   # ★ 算法单测（期望值来自桌面端）
```

---

## 开发环境

| 项 | 版本/位置 |
|---|---|
| Flutter | 3.47.5 stable |
| Dart | 3.13.4 |
| Android SDK | `D:\Android\Sdk`（platform-36, build-tools 36.1.0） |
| Java | 17.0.19 |

### 常用命令

```bash
flutter pub get                 # 装依赖
flutter test test/stats/        # 跑统计算法单测（重要！）
flutter analyze                 # 静态检查
flutter run -d <device>         # 跑起来
flutter build apk --release     # 打安卓包
```

---

## 开发原则

1. **算法先对齐，再写 UI** —— 数据不对，UI 再漂亮也没意义
2. **改算法必须先读 `docs/metrics-contract.md`** —— 且确认桌面端是否也该改
3. **常量测试不能为了"通过"而改断言值** —— 那是掩盖口径漂移
4. **FIT 解析适配层是风险最高的地方** —— 详见 `lib/core/fit/README.md`

---

## 分阶段路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 装 Flutter SDK + 项目骨架 | 进行中 |
| P1 | FIT 解析适配 + 统计算法 + 单测 | 算法已完成，待实测验证 |
| P2 | drift 数据库 + 本地文件导入 | 未开始 |
| P3 | 活动列表 + 单次深度分析 | 未开始 |
| P4 | 月度 / 年度 / 趋势统计 | 未开始 |
| P5 | 多平台数据源 | 未开始 |
| P6 | 训练负荷 + PR + 通勤打标 | 未开始 |
| P7 | AI 分析 | 未开始 |
| P8 | 装备管理 / 导出 / 地图 | 未开始 |

---

## 参考项目

`sports-data-sync-multiplatform-main`（鸡翅幸哲迈进OB）—— 安卓多平台运动数据同步工具。

**借鉴范围：** 各平台登录/拉取协议（`api/*Api.kt`）、FIT 二进制结构理解。

**⚠️ 许可证警示：** 该仓库 README 标注 MIT 但**根目录无 LICENSE 文件**，
`THANKS.md` 列出 6 个上游算法来源 → **只借鉴协议逻辑，代码自己重写**。
