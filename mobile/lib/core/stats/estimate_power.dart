/// 从速度/海拔/加速度估算功率（无功率计时使用）。
///
/// 移植自 `core/analysis.py::estimate_power`。
///
/// 基于物理模型：P = (F_roll + F_air + F_gravity + F_accel) × v
/// - F_roll    = Crr × m × g × cos(θ)
/// - F_air     = 0.5 × ρ × CdA × v²
/// - F_gravity = m × g × sin(θ)，θ 由 5 点平滑海拔差 / 水平距离求坡度
/// - F_accel   = m × a，a 由 5 点平滑速度差求，clamp ±1.5 m/s²
///
/// ⚠️ **估算功率不得当作实测功率**：导出/展示/TSS 都不能用。
/// 这一点与桌面端一致（见 `training_load.dart::computeActivityTss` 里的
/// `powerEstimated` 检查）。
library;

import 'dart:math' as math;

import '../models/activity_record.dart';
import '../utils/py_round.dart';

/// 估算功率参数。默认值对齐桌面端 `core/config.py`。
class PowerEstimateConfig {
  final double riderWeightKg;
  final double bikeWeightKg;
  final double crr;
  final double cda;
  final double airDensity;

  const PowerEstimateConfig({
    this.riderWeightKg = 70.0,
    this.bikeWeightKg = 10.0,
    this.crr = 0.005,
    this.cda = 0.35,
    this.airDensity = 1.225,
  });
}

/// 平滑窗口大小（点）。桌面端硬编码 W=5。
const int _smoothWindow = 5;

/// 重力加速度。
const double _g = 9.80665;

/// 坡度上下限（±25%）。
const double _maxGrade = 0.25;

/// 加速度上下限（±1.5 m/s²）。
const double _maxAccel = 1.5;

/// 从速度/海拔/加速度估算功率。
///
/// 移植自 `core/analysis.py::estimate_power`。
///
/// **若 records 已有功率计数据（任一非 null 且非估算），直接返回原数据。**
///
/// 返回新列表，估算出的记录 `power` 有值且 `powerEstimated = true`。
List<ActivityRecord> estimatePower(
  List<ActivityRecord> records, {
  PowerEstimateConfig config = const PowerEstimateConfig(),
}) {
  // 如果已有功率计数据，不估算
  if (records.any((r) => r.power != null)) {
    return records;
  }

  final totalMass = config.riderWeightKg + config.bikeWeightKg;

  // 平滑海拔 / 速度：5 点滑动窗口（尾部窗口，含当前点）
  final smoothAlt = _smooth(records, (r) => r.altM);
  final smoothSpeed = _smooth(records, (r) => r.speedMs);

  final result = <ActivityRecord>[];
  for (var i = 0; i < records.length; i++) {
    final r = records[i];
    final speed = smoothSpeed[i] ?? 0.0;
    final alt = smoothAlt[i];

    // 坡度：5 点平滑海拔差 / 水平距离
    var grade = 0.0;
    if (alt != null && i >= _smoothWindow && smoothAlt[i - _smoothWindow] != null) {
      final hDist = (r.distM ?? 0) - (records[i - _smoothWindow].distM ?? 0);
      if (hDist > 1.0) {
        grade = (alt - smoothAlt[i - _smoothWindow]!) / hDist;
        grade = math.max(-_maxGrade, math.min(_maxGrade, grade));
      }
    }

    final theta = grade.abs() > 0.0005 ? math.atan(grade) : 0.0;

    final fRoll = config.crr * totalMass * _g * math.cos(theta);
    final fAir = 0.5 * config.airDensity * config.cda * speed * speed;
    final fGravity = totalMass * _g * math.sin(theta);

    // 加速度：5 点平滑速度差
    var fAccel = 0.0;
    if (i >= _smoothWindow && smoothSpeed[i - _smoothWindow] != null) {
      final dt = r.t - records[i - _smoothWindow].t;
      if (dt > 0) {
        var a = (speed - smoothSpeed[i - _smoothWindow]!) / dt;
        a = math.max(-_maxAccel, math.min(_maxAccel, a));
        fAccel = totalMass * a;
      }
    }

    final power = (fRoll + fAir + fGravity + fAccel) * speed;

    result.add(ActivityRecord(
      t: r.t,
      lat: r.lat,
      lon: r.lon,
      distM: r.distM,
      speedMs: r.speedMs,
      hr: r.hr,
      cad: r.cad,
      altM: r.altM,
      temp: r.temp,
      power: pyRound(math.max(0.0, power)).toDouble(),
      powerEstimated: true,
    ));
  }

  return result;
}

/// 5 点尾部滑动窗口平滑。对齐桌面端 `_smooth`：
/// 窗口内**忽略 null**，无可用的则返回 null。
List<double?> _smooth(
  List<ActivityRecord> records,
  double? Function(ActivityRecord) getter,
) {
  final out = <double?>[];
  for (var i = 0; i < records.length; i++) {
    final start = math.max(0, i - _smoothWindow + 1);
    final vals = <double>[];
    for (var j = start; j <= i; j++) {
      final v = getter(records[j]);
      if (v != null) vals.add(v);
    }
    out.add(vals.isEmpty ? null : vals.reduce((a, b) => a + b) / vals.length);
  }
  return out;
}
