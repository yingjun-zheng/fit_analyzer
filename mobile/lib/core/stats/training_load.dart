/// 训练负荷：TSS / NP / IF + CTL/ATL/TSB 三指标（教练视角的疲劳监控）。
///
/// 移植自 `core/training_load.py`，参考 Andy Coggan 的训练压力理论：
/// - NP（归一化功率）：对逐秒功率做 30 秒平均后取四次方再均值开四次方，反映等效强度。
/// - IF（强度因子）= NP / FTP。
/// - TSS（训练压力分数）= (秒 × NP × IF) / (FTP × 3600) × 100。
/// - CTL（长期体能/慢性负荷）：TSS 的 42 天指数加权。
/// - ATL（短期疲劳/急性负荷）：TSS 的 7 天指数加权。
/// - TSB（状态）= CTL - ATL，正值偏"恢复/状态佳"，负值偏"疲劳"。
///
/// 无功率数据时的降级：
/// - 若有心率 → 用 hrTSS（基于心率区间的训练压力）。
/// - 若都无 → 返回 null（不猜）。
library;

import 'dart:math' as math;

import '../models/activity_record.dart';
import '../utils/py_round.dart';
import 'metrics.dart';

/// NP（归一化功率，瓦）。
///
/// 移植自 `core/training_load.py::normalized_power`。
///
/// 返回 (np, avgPower)。无功率数据时返回 (null, null)。
({double? np, double? avgPower}) normalizedPower(
  List<ActivityRecord> records,
) {
  final powers = <double>[];
  for (final r in records) {
    if (r.power != null) powers.add(r.power!);
  }
  if (powers.isEmpty) return (np: null, avgPower: null);

  final avg = powers.fold<double>(0.0, (a, b) => a + b) / powers.length;

  // 30 秒滚动平均后再四次方
  final n = powers.length;
  final window = math.min(30, n);
  final smoothed = <double>[];
  for (var i = 0; i < n; i++) {
    final start = math.max(0, i - window + 1);
    final win = powers.sublist(start, i + 1);
    smoothed.add(win.fold<double>(0.0, (a, b) => a + b) / win.length);
  }

  var meanFourth = 0.0;
  for (final p in smoothed) {
    meanFourth += math.pow(p, 4).toDouble();
  }
  meanFourth /= smoothed.length;
  final npVal = math.pow(meanFourth, 0.25).toDouble();

  return (np: _round1(npVal), avgPower: _round1(avg));
}

/// 功率 TSS。移自 `core/training_load.py::_tss_from_power`。
double? _tssFromPower(List<ActivityRecord> records, double? ftp) {
  if (ftp == null || ftp <= 0) return null;
  final np = normalizedPower(records).np;
  if (np == null) return null;

  final ts = <double>[];
  for (final r in records) {
    ts.add(r.t);
  }
  final seconds =
      ts.length >= 2 ? (ts.reduce(math.max) - ts.reduce(math.min)) : records.length.toDouble();
  if (seconds <= 0) return null;

  final intensity = np / ftp;
  return _round1((seconds * np * intensity) / (ftp * 3600.0) * 100.0);
}

/// 心率 TSS（hrTSS）近似。移自 `core/training_load.py::_tss_from_hr`。
///
/// 用「等效强度因子 IF」框架：每档心率区映射一个 IF（0~1），
/// TSS = Σ(每区时长小时 × IF²) × 100。
double? _tssFromHr(List<ActivityRecord> records, double? maxHr) {
  if (maxHr == null || maxHr <= 0) return null;

  final zoneSeconds = List<double>.filled(5, 0.0);
  final n = records.length;

  for (var i = 0; i < n; i++) {
    final v = records[i].hr;
    if (v == null) continue;

    var dt = 1.0;
    if (i + 1 < n) {
      final nxtT = records[i + 1].t;
      final curT = records[i].t;
      dt = math.max(0.0, math.min(nxtT - curT, maxZoneDtSeconds));
    }

    var zone = 0;
    for (final p in hrZonePcts) {
      if (v >= maxHr * p) {
        zone += 1;
      } else {
        break;
      }
    }
    zone = math.min(zone, 4);
    zoneSeconds[zone] += dt;
  }

  var total = 0.0;
  for (var i = 0; i < 5; i++) {
    total += (zoneSeconds[i] / 3600.0) * math.pow(hrZoneIntensityFactors[i], 2).toDouble() * 100.0;
  }
  return _round1(total);
}

/// 计算单次活动的 TSS。
///
/// 移植自 `core/training_load.py::compute_activity_tss`。
///
/// 优先级：功率计 FTP TSS > 心率 hrTSS > null。
/// ⚠️ 估算功率（powerEstimated）误差过大，**不得用于 TSS**，等同无功率走心率降级。
ActivityTss computeActivityTss(
  List<ActivityRecord> records, {
  double? ftp,
  double? maxHr,
}) {
  final hasPower = records.any((r) => r.power != null && !r.powerEstimated);

  if (hasPower && ftp != null && ftp > 0) {
    final npv = normalizedPower(records);
    final tss = _tssFromPower(records, ftp);
    if (tss != null) {
      final intensity = npv.np != null ? _round2(npv.np! / ftp) : null;
      return ActivityTss(
        tss: tss,
        method: 'power',
        npW: npv.np,
        avgW: npv.avgPower,
        intensity: intensity,
      );
    }
  }

  if (maxHr != null && maxHr > 0) {
    final tss = _tssFromHr(records, maxHr);
    if (tss != null) {
      return ActivityTss(tss: tss, method: 'hr');
    }
  }

  return const ActivityTss();
}

/// 按日历天连续计算指数加权移动平均（正确版本）。
///
/// 移植自 `core/training_load.py::_ewma_daily`。
///
/// **关键**：空档天数也参与衰减 —— 对缺失的日期 tss=0，逐日推进。这样
/// 数月的训练空档会让 CTL/ATL 正确衰减，而不是错误地保持高位。
///
/// [dailyTss] 按日期升序的 [(dateStr, tss)] 列表。
/// 返回 {dateStr: ewmaValue}，仅包含有活动的日期。
Map<String, double> _ewmaDaily(List<(String, double)> dailyTss, double tau) {
  final alpha = 1 - math.exp(-1.0 / tau);
  final result = <String, double>{};
  double? prev;
  DateTime? prevDate;

  for (final entry in dailyTss) {
    final dateStr = entry.$1;
    final tss = entry.$2;
    final d = DateTime.parse(dateStr);

    if (prev == null) {
      prev = tss;
      prevDate = d;
    } else {
      // 先按空档天数衰减（每天 tss=0 推进一次）
      final gapDays = d.difference(prevDate!).inDays;
      for (var i = 0; i < math.max(0, gapDays - 1); i++) {
        prev = prev! + alpha * (0 - prev);
      }
      // 当天有负荷
      prev = prev! + alpha * (tss - prev);
      prevDate = d;
    }
    result[dateStr] = prev;
  }
  return result;
}

/// 由每日 TSS 序列计算 CTL/ATL/TSB 曲线（按日历天连续衰减）。
///
/// 移植自 `core/training_load.py::build_performance_curve`。
PerformanceCurve buildPerformanceCurve(List<(String, double)> dailyTss) {
  final dates = [for (final e in dailyTss) e.$1];
  final ctls = _ewmaDaily(dailyTss, ctlTau);
  final atls = _ewmaDaily(dailyTss, atlTau);

  final tsbs = <String, double?>{};
  for (final d in dates) {
    if (ctls.containsKey(d) && atls.containsKey(d)) {
      tsbs[d] = _round1(ctls[d]! - atls[d]!);
    } else {
      tsbs[d] = null;
    }
  }

  final latestDate = dates.isNotEmpty ? dates.last : null;
  PerformanceSnapshot? latest;
  if (latestDate != null) {
    latest = PerformanceSnapshot(
      date: latestDate,
      ctl: _round1(ctls[latestDate]!),
      atl: _round1(atls[latestDate]!),
      tsb: tsbs[latestDate],
    );
  }

  return PerformanceCurve(ctl: ctls, atl: atls, tsb: tsbs, latest: latest);
}

/// 最近 N 个自然日的 TSS 合计（不是"最后 N 条记录"）。
///
/// 移植自 `core/training_load.py::recent_week_tss`。
double recentWeekTss(List<(String, double)> dailyTss, {int days = 7}) {
  if (dailyTss.isEmpty) return 0.0;
  final anchor = DateTime.parse(dailyTss.last.$1);
  final start = anchor.subtract(Duration(days: days - 1));

  var total = 0.0;
  for (final e in dailyTss) {
    final d = DateTime.parse(e.$1);
    if (!d.isBefore(start) && !d.isAfter(anchor)) {
      total += e.$2;
    }
  }
  return _round1(total);
}

/// 把多条活动的 (date, tss) 聚合成每日总和，按日期升序。
///
/// 移植自 `core/training_load.py::daily_tss_from_activities`。
List<(String, double)> dailyTssFromActivities(List<(String, double?)> acts) {
  final agg = <String, double>{};
  for (final e in acts) {
    if (e.$2 != null) {
      agg[e.$1] = (agg[e.$1] ?? 0) + e.$2!;
    }
  }
  final keys = agg.keys.toList()..sort();
  return [for (final k in keys) (k, agg[k]!)];
}

/// 根据 TSB 给出恢复/训练提示文本。
///
/// 移植自 `core/training_load.py::recovery_advice`。
String recoveryAdvice(double? tsb) {
  if (tsb == null) {
    return '缺训练负荷数据，无法评估疲劳状态。';
  }
  if (tsb < -30) {
    return 'TSB=$tsb，深度疲劳，建议休息或轻松恢复骑行，避免高强度。';
  }
  if (tsb < -10) {
    return 'TSB=$tsb，疲劳累积，可安排低强度有氧，避免连续高强度。';
  }
  if (tsb <= 10) {
    return 'TSB=$tsb，负荷适中，可按计划正常训练。';
  }
  if (tsb <= 25) {
    return 'TSB=$tsb，恢复充分、状态良好，适合安排高强度或比赛。';
  }
  return 'TSB=$tsb，过度恢复（训练量偏低），可适度上量。';
}

// ---------------- 内部工具 ----------------

/// 对齐桌面端 `round(v, 1)`（Python 银行家舍入）。
double _round1(double v) => pyRoundTo(v, 1);

/// 对齐桌面端 `round(v, 2)`（Python 银行家舍入）。
double _round2(double v) => pyRoundTo(v, 2);

// ---------------- 结果类型 ----------------

class ActivityTss {
  final double? tss;
  final String? method;
  final double? npW;
  final double? avgW;
  final double? intensity;
  const ActivityTss({this.tss, this.method, this.npW, this.avgW, this.intensity});
}

class PerformanceSnapshot {
  final String date;
  final double ctl;
  final double atl;
  final double? tsb;
  const PerformanceSnapshot({
    required this.date,
    required this.ctl,
    required this.atl,
    this.tsb,
  });
}

class PerformanceCurve {
  final Map<String, double> ctl;
  final Map<String, double> atl;
  final Map<String, double?> tsb;
  final PerformanceSnapshot? latest;
  const PerformanceCurve({
    required this.ctl,
    required this.atl,
    required this.tsb,
    this.latest,
  });
}
