/// 统计口径常量。
///
/// ⚠️ 这些常量**必须与 fit_analyzer 桌面端逐字一致**（`core/analysis.py`）。
/// 它们不是"可调参数"，而是算法正确性的一部分 —— 改一个数字，两端（或将来重装
/// 的同一 App 不同版本）就会算出不同结果。修改前请先读 `docs/metrics-contract.md`。
library;

/// 海拔噪声阈值（米）。来自 `core/analysis.py` 的 `ALTITUDE_NOISE_THRESHOLD_M`。
///
/// 累计变化达到该值才计入爬升/下降，并把参考点移到当前值。
/// 阈值内的小幅抖动不会灌水（朴素"正增量全加"会把 ±噪声全累成爬升）。
const double altitudeNoiseThresholdM = 1.0;

/// 移动时间判定阈值（m/s）。来自 `core/analysis.py` 的 `moving_time()`。
///
/// 速度 > 0.5 m/s 视为"在移动"。
const double movingSpeedThresholdMs = 0.5;

/// 区间时间加权的单点时间差上限（秒）。来自 `core/analysis.py` 的 `_weighted_zone_times`。
///
/// dt = min(下一条 t − 当前 t, 30.0)；dt == 0 时取 1.0。
const double maxZoneDtSeconds = 30.0;

/// 速度曲线抽稀默认点数。来自 `core/analysis.py` 的 `downsample_series(max_points=600)`。
const int defaultSeriesMaxPoints = 600;

/// 轨迹抽稀默认点数。来自 `core/analysis.py` 的 `track_points(max_points=2000)`。
const int defaultTrackMaxPoints = 2000;

/// 心率区间边界（最大心率百分比）。来自 `core/training_load.py` 的 `_lactate_zones_pcts()`。
const List<double> hrZonePcts = [0.6, 0.7, 0.8, 0.9];

/// 心率区映射的等效强度因子（用于 hrTSS）。来自 `core/training_load.py` 的 `_tss_from_hr`。
const List<double> hrZoneIntensityFactors = [0.50, 0.65, 0.75, 0.85, 0.95];

/// CTL（长期体能）指数加权时间常数（天）。来自 `core/training_load.py`。
const double ctlTau = 42.0;

/// ATL（短期疲劳）指数加权时间常数（天）。来自 `core/training_load.py`。
const double atlTau = 7.0;
