# 🚴 骑行FIT数据分析器（Fit Analyzer）

免费、本地运行的**骑行 FIT 数据离线分析软件**（纯桌面 Windows 应用，PySide6 原生界面，无浏览器、无本地服务），参考 Garmin Connect / 行者 的骑行数据分析功能：

- **纯桌面图形界面**（原生窗口），**批量导入**码表导出的 `.fit` 文件（iGPSPORT / Garmin / 行者等主流设备），SQLite 本地存储
- 单条活动显示：**记录时间、平均速度、卡路里、最大速度、平均心率、平均踏频、累计爬升** 等 16+ 项指标
- **速度按公里折线图**、**速度区间统计**、**心率统计与心率区间**、**踏频统计与踏频区间**、**海拔统计**、**设备温度统计**
- **记圈（赛段）数据详情**、**活动详情全部字段**
- **运动轨迹图**：高德在线地图（可选）或固定背景图片 + 轨迹叠加（起终点标记、海拔范围）
- **按月汇总统计**：各月次数/里程/用时/爬升/消耗，跨月折线图
- **AI 数据分析**：接入本地 AI（Ollama / LM Studio / vLLM）或任意 OpenAI 兼容远程模型（DeepSeek 等，用自己的 Key），生成单次活动分析报告与月度训练总结
- **GPX 导出**：单条活动导出为 GPX 1.1 格式（含 Garmin TrackPointExtension 扩展：心率/踏频/温度/速度/功率），兼容 Strava / Garmin Connect / 行者等平台
- 内置**日志系统**（滚动文件 + 界面实时查看）

---

## 一、运行

### 打包好的 EXE（推荐）
`dist\骑行FIT数据分析器\骑行FIT数据分析器.exe` 双击运行（无控制台窗口，关闭窗口即退出）。

### 源码运行
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## 二、使用

1. 打开软件 → 工具栏「**批量导入 FIT 文件**」，多选码表导出的 `.fit`（可一次性选几百个；重复导入自动更新不重复）。
2. 左侧按月列出训练记录，点击某月查看**月度汇总**（次数/里程/用时/爬升/消耗 + 跨月折线图 + 活动列表，双击活动进入详情）。
3. 点击单条活动进入详情（标签页）：
   - **概览**：16+ 项指标卡 + 每公里均速折线图 + 速度/心率/踏频/海拔全程曲线 + 设备温度曲线
   - **区间统计**：速度区间、心率区间（Z1~Z5，按最大心率百分比）、踏频区间（按时间权重）+ 占比文字
   - **记圈**：每圈开始时间/时长/距离/均速/最大速度/心率/踏频/卡路里/爬升/下降
   - **轨迹**：固定背景图片上的轨迹图（起终点标记、海拔范围）
   - **活动详情**：全部字段（含设备、运动类型、文件、导入时间等）
   - **AI 分析**：点「生成 AI 分析报告」

## 三、AI 接入（可选，免费）

设置 → AI：

| 场景 | 地址 | 说明 |
| --- | --- | --- |
| Ollama（本地） | `http://127.0.0.1:11434/v1` | `ollama list` 查看已拉取模型，填准确模型名（如 `qwen3.5-4b:latest`） |
| LM Studio（本地） | `http://127.0.0.1:1234/v1` | 加载任意 GGUF |
| DeepSeek / OpenAI | `https://api.deepseek.com/v1` | 填自己的 Key |

> 模型名填错会提示 404，并**自动列出服务器上可用的模型**方便修改。

启用后：
- 单条活动 →「生成 AI 分析报告」：整体评价、强度节奏分析（心率区间/速度分布）、问题与训练建议
- 月度视图 →「AI 月度总结」：训练量、强度结构、规律性、下月建议

AI 调用全部走你配置的地址，软件不内置任何收费接口，Key 本地保存并脱敏。

## 四、统计口径

- **心率区间**：按最大心率百分比 5 区（默认 60/70/80/90%），最大心率取数据内最大值或手动覆盖；无心率数据的活动自动隐藏心率分析
- **速度区间 / 踏频区间**：阈值可在 设置→统计区间 调整（速度默认 10~35km/h 每 5 一档；踏频默认 60~100rpm 每 10 一档）
- **区间时长**：按逐条记录的时间权重累加
- **海拔/温度/心率/踏频曲线**：自动抽稀（≤600 点），轨迹抽稀 ≤2000 点

## 五、轨迹图

「轨迹」页支持两种模式，自动切换：

1. **高德在线地图（推荐，可选）**：在 `设置 → 高德地图` 填入你在[高德开放平台](https://lbs.amap.com/)申请的「**Web端(JS API)**」类型 key 与安全密钥后，轨迹直接叠加在真实地图上（自绘起终点标记、前端 WGS-84→GCJ-02 纠偏贴合道路）。
   - 如何申请：高德开放平台 → 控制台 → 应用管理 → 创建应用 → 添加 key，**服务平台务必选「Web端(JS API)」**，并在「设置」中生成/查看**安全密钥 securityJsCode**。
   - key 会明文存于本地配置并写进内嵌网页，仅供本地渲染；建议在控制台给 key 配好**域名白名单**（桌面端来源为空时白名单留空即可）。
   - **依赖**：需环境中能加载 `PySide6` 的 WebEngine 组件（`PySide6-Addons` / 完整 `PySide6`）。打包单文件时 WebEngine 组件较大，请确认 build 脚本已包含 QtWebEngine 资源。
2. **固定背景图（默认）**：未配置 key，或运行环境缺 WebEngine 组件时，自动回退——从 `backgrounds\` 目录随机选一张图片作背景，轨迹按 GPS 包围盒缩放适配。此时轨迹页**底部小字**会提示"未配置高德地图 Key"或"缺少 WebEngine 组件"。
   - 想换/增加背景：把图片（jpg/jpeg/png 等）放进 `backgrounds\` 文件夹（源码版）后重新打包即可；没有该目录时回退到根目录 `back9.jpeg`。
- 轨迹为逐秒定位点的近似连线；无 GPS 数据时该页提示无轨迹。

## 六、数据与日志

- 数据目录：`%APPDATA%\FitAnalyzer\`
  - `fit.db` SQLite 数据库（活动/记圈/逐条记录）
  - `logs\fit_analyzer.log` 滚动日志（2MB×5 份）
- 工具栏「日志」可实时查看（自动刷新）；「数据目录」直接打开数据文件夹。
- 命令行参数：`--data-dir`（自定义数据目录）、`--debug`（详细日志）、`--selftest`（离屏自检）。

## 七、重新打包 EXE

```powershell
powershell -ExecutionPolicy Bypass -File build\build_exe.ps1        # 目录版
powershell -ExecutionPolicy Bypass -File build\build_exe.ps1 -OneFile
```

> 打包环境需同时具备 `PySide6`（含 WebEngine 组件，完整版或 `PySide6-Addons`）+ `pyinstaller` + `pillow` + `fitparse`。
> **WebEngine 已通过 `build\fit_analyzer.spec` 的 `hiddenimports` 显式纳入**（`QtWebEngineWidgets`/`QtWebEngineCore`/`QtWebChannel`），打包后产物约 500MB+，属正常（含 `QtWebEngineProcess.exe`、`resources.pak`、`qtwebengine_locales`）。
> 生成目录版后建议用 `骑行FIT数据分析器.exe --selftest` 做一次离屏自检，确认 WebEngine/主程序正常。

## 八、项目结构

```
fit_analyzer/
├── app.py                # 入口（PySide6；含 --selftest 离屏自检）
├── gui/
│   ├── main_window.py    # 主窗口：月份-活动树 / 月度汇总 / 活动详情标签页
│   ├── charts.py         # QtCharts 图表封装（折线/柱状/区间）
│   ├── track_widget.py   # 轨迹控件（固定背景图 + 轨迹）
│   ├── amap_track.py     # TrackMapPanel：高德在线地图 / 图片背景 自动切换
│   ├── dialogs.py        # 设置 / 日志对话框
│   └── theme.py          # 样式与格式化
├── core/
│   ├── fit_parser.py     # FIT 解析（fitparse，兼容缺字段/缺心率/本地时区）
│   ├── db.py             # SQLite 存储与月度汇总
│   ├── analysis.py       # 分公里/区间/曲线/轨迹统计
│   ├── gpx_export.py     # GPX 1.1 导出（含心率/踏频/温度/速度/功率扩展）
│   ├── ai_client.py      # OpenAI 兼容客户端（含模型不存在提示）
│   ├── ai_analysis.py    # 活动/月度 AI 分析提示词
│   ├── month_agent.py    # 月度骑行数据查询 Agent（工具调用回答「某月训练」问题）
│   └── config.py / logging_setup.py / http_utils.py
├── back9.jpeg            # 轨迹背景图
├── build/                # PyInstaller spec + 打包脚本
└── tests/smoke_test.py   # 核心冒烟测试（真实数据）
```

## 九、已知限制

- FIT 文件里**没有的数据**（如某些码表不记录心率/功率）界面显示「—」，不影响其他统计。
- 轨迹为逐秒定位点的近似连线；部分设备只在 10 秒级采样，轨迹会呈折线状。
- 仅支持骑行类 FIT；如导入其他运动类型也会按记录解析（sport 字段原样保留）。

###  目前已测试数据的码表（欢迎提供各大品牌码表数据供测试）
- IGP BSC200
- IGP BSC300
- 百锐腾 Rider 15（产品码 1801，已映射为 Rider 15，若实为其他型号请在「设置 → 设备型号表」覆盖）
- 迈金Magene C606 pro
