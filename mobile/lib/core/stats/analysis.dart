/// 核心统计口径实现。
///
/// ⚠️ **本文件的每个算法都从 fit_analyzer 桌面端逐行移植**，对应关系见
/// `docs/metrics-contract.md`。移植原则：
///   1. 算法逻辑完全一致（包括边界处理）
///   2. 常量从 `metrics.dart` 引用，不硬编码
///   3. 保留桌面端的注释意图，便于将来对照
///
/// 为什么不能直接用 FIT 文件自带的汇总值？
///   见 `docs/metrics-contract.md` §为什么必须自己算。
library;

import 'dart:math' as math;

import '../models/activity_record.dart';
import '../utils/py_round.dart';
import 'metrics.dart';

/// 带滞回的爬升/下降累计（参考点法），滤除 GPS/气压计海拔噪声。
///
/// 移植自 `core/analysis.py::accumulate_ascent_descent`。
///
/// 维护一个参考海拔：海拔相对参考点的累计变化达到 [threshold] 时，
/// 才把这段变化计入爬升/下降并把参考点移到当前值。阈值内的小幅抖动
/// 不会灌水（朴素「正增量全加」算法会把 ±噪声 全部累成爬升）；
/// 持续爬升/下降正常累计，仅整段末尾不足阈值的部分不计
/// （全程最多低估 threshold 米，可忽略）。
///
/// 返回 (ascent, descent)，单位米。
({double ascent, double descent}) accumulateAscentDescent(
  List<double?> eles, {
  double threshold = altitudeNoiseThresholdM,
}) {
  var ascent = 0.0;
  var descent = 0.0;
  double? ref;

  for (final ele in eles) {
    if (ele == null) continue;
    if (ref == null) {
      ref = ele;
      continue;
    }
    final d = ele - ref;
    if (d >= threshold) {
      ascent += d;
      ref = ele;
    } else if (d <= -threshold) {
      descent += -d;
      ref = ele;
    }
  }
  return (ascent: ascent, descent: descent);
}

/// 移动时间估算：速度 > [movingSpeedThresholdMs] 视为移动。
///
/// 移植自 `core/analysis.py::moving_time`。
///
/// 注意与 FIT 自带 `total_moving_time`、以及用 events（暂停/恢复）算的
/// 计时时间都不同 —— 这是桌面端的口径，必须照搬。
double movingTime(List<ActivityRecord> records) {
  var mt = 0.0;
  for (var i = 0; i < records.length; i++) {
    if ((records[i].speedMs ?? 0) > movingSpeedThresholdMs) {
      var dt = 1.0;
      if (i + 1 < records.length) {
        final nxt = records[i + 1].t;
        final cur = records[i].t;
        dt = math.max(0.0, nxt - cur);
      }
      mt += dt;
    }
  }
  return mt;
}

/// 按记录的时间权重统计各区间秒数。
///
/// 移植自 `core/analysis.py::_weighted_zone_times`。
///
/// [records] 需按 t 升序。[boundaries] 为区间上边界列表（升序）。
/// [valueKey] 取值函数（如取心率、功率、速度）。
///
/// 关键点：每条记录的时间权重 `dt = min(下一条 t − 当前 t, maxZoneDtSeconds)`，
/// 而不是"每条算 1 秒"。最后一条没有下一条，dt 取 1.0。
///
/// 返回每个区间的 {zone, seconds, pct}。
List<ZoneTime> weightedZoneTimes(
  List<ActivityRecord> records,
  double? Function(ActivityRecord) valueGetter,
  List<double> boundaries,
) {
  final zones = List<double>.filled(boundaries.length + 1, 0.0);

  for (var i = 0; i < records.length; i++) {
    final v = valueGetter(records[i]);
    if (v == null) continue;

    var dt = 1.0;
    if (i + 1 < records.length) {
      final nxt = records[i + 1].t;
      final cur = records[i].t;
      dt = math.max(0.0, math.min(nxt - cur, maxZoneDtSeconds));
      if (dt == 0) dt = 1.0;
    }

    var idx = 0;
    for (final b in boundaries) {
      if (v >= b) {
        idx += 1;
      } else {
        break;
      }
    }
    zones[idx] += dt;
  }

  final total = zones.fold<double>(0.0, (a, b) => a + b);
  return [
    for (var i = 0; i < zones.length; i++)
      ZoneTime(
        zone: i + 1,
        seconds: _round1(zones[i]),
        pct: total > 0 ? _round1(zones[i] / total * 100) : 0.0,
      ),
  ];
}

/// 时间序列抽稀（等间隔采样）为 [{t, v}]。
///
/// 移植自 `core/analysis.py::downsample_series`。
///
/// ⚠️ 抽稀点数会影响曲线形状。用 [defaultSeriesMaxPoints] 与桌面端一致。
List<SeriesPoint> downsampleSeries(
  List<ActivityRecord> records,
  double? Function(ActivityRecord) valueGetter, {
  int maxPoints = defaultSeriesMaxPoints,
}) {
  final pts = <(double, double)>[];
  for (final r in records) {
    final v = valueGetter(r);
    if (v != null) pts.add((r.t, v));
  }

  if (pts.length <= maxPoints) {
    return [for (final p in pts) SeriesPoint(t: p.$1, v: p.$2)];
  }

  final step = pts.length / maxPoints;
  final out = <SeriesPoint>[];
  for (var i = 0; i < maxPoints; i++) {
    final idx = math.min(pts.length - 1, (i * step).floor());
    out.add(SeriesPoint(t: pts[idx].$1, v: pts[idx].$2));
  }
  return out;
}

/// 海拔序列（横轴用距离 km）。
///
/// 移植自 `core/analysis.py::elevation_series`。
List<SeriesPoint> elevationSeries(
  List<ActivityRecord> records, {
  int maxPoints = defaultSeriesMaxPoints,
}) {
  final items = <ActivityRecord>[];
  for (final r in records) {
    if (r.altM != null) items.add(r);
  }

  // 桌面端先构造 {t: 距离km, v: 海拔} 再用 downsample_series 处理
  if (items.length <= maxPoints) {
    return [
      for (final r in items)
        SeriesPoint(t: (r.distM ?? 0) / 1000.0, v: r.altM!),
    ];
  }
  final step = items.length / maxPoints;
  final out = <SeriesPoint>[];
  for (var i = 0; i < maxPoints; i++) {
    final idx = math.min(items.length - 1, (i * step).floor());
    final r = items[idx];
    out.add(SeriesPoint(t: (r.distM ?? 0) / 1000.0, v: r.altM!));
  }
  return out;
}

/// 按 1km 分桶：每公里时间/均速/最大速度/平均心率/平均踏频/平均海拔。
///
/// 移植自 `core/analysis.py::per_km`。
List<PerKmBucket> perKm(List<ActivityRecord> records) {
  final buckets = <_RawBucket>[];
  _RawBucket? cur;

  for (final r in records) {
    final dist = r.distM ?? 0.0;
    final km = dist ~/ 1000.0;

    if (cur == null || cur.km != km) {
      if (cur != null) buckets.add(cur);
      cur = _RawBucket(
        km: km,
        t0: r.t,
        t1: r.t,
        dist0: dist,
        dist1: dist,
      );
    }
    cur.t1 = r.t;
    cur.dist1 = dist;
    if (r.speedMs != null) cur.speeds.add(r.speedMs!);
    if (r.hr != null) cur.hrs.add(r.hr!);
    if (r.cad != null) cur.cads.add(r.cad!);
    if (r.altM != null) cur.alts.add(r.altM!);
  }
  if (cur != null) buckets.add(cur);

  final out = <PerKmBucket>[];
  for (final b in buckets) {
    final dt = b.t1 - b.t0;
    final segDist = (b.dist1 - b.dist0) / 1000.0;
    final avgSpeed = dt > 0 ? (segDist / dt * 3600.0) : null;

    out.add(PerKmBucket(
      km: b.km,
      timeS: dt > 0 ? _round1(dt) : 0.0,
      avgSpeedKmh: avgSpeed != null ? _round1(avgSpeed) : null,
      maxSpeedKmh:
          b.speeds.isNotEmpty ? _round1(b.speeds.reduce(math.max) * 3.6) : null,
      avgHr: b.hrs.isNotEmpty ? _round0(_avg(b.hrs)) : null,
      maxHr: b.hrs.isNotEmpty ? _round0(b.hrs.reduce(math.max)) : null,
      avgCad: b.cads.isNotEmpty ? _round0(_avg(b.cads)) : null,
      avgAlt: b.alts.isNotEmpty ? _round1(_avg(b.alts)) : null,
    ));
  }
  return out;
}

/// 轨迹抽稀：保留经纬度点（含海拔），均匀采样。
///
/// 移植自 `core/analysis.py::track_points`。
///
/// 注意桌面端用 `round(i * step)` 且 step = (n-1)/(maxPoints-1)，并保证首尾。
List<TrackPoint> trackPoints(
  List<ActivityRecord> records, {
  int maxPoints = defaultTrackMaxPoints,
}) {
  final pts = <(double, double, double?)>[];
  for (final r in records) {
    if (r.lat != null && r.lon != null) {
      pts.add((r.lat!, r.lon!, r.altM));
    }
  }
  if (pts.isEmpty) return [];

  if (pts.length <= maxPoints) {
    return [
      for (final p in pts) TrackPoint(lat: p.$1, lon: p.$2, altM: p.$3),
    ];
  }

  final step = (pts.length - 1) / (maxPoints - 1);
  final out = <TrackPoint>[];
  for (var i = 0; i < maxPoints; i++) {
    // 桌面端 `int(round(i * step))` → Python 银行家舍入
    final idx = pyRound(i * step);
    out.add(TrackPoint(lat: pts[idx].$1, lon: pts[idx].$2, altM: pts[idx].$3));
  }
  // 保证首尾
  if (out.last.lat != pts.last.$1 || out.last.lon != pts.last.$2) {
    out[out.length - 1] =
        TrackPoint(lat: pts.last.$1, lon: pts.last.$2, altM: pts.last.$3);
  }
  return out;
}

/// 温度统计。移植自 `core/analysis.py::temp_stats`。
TempStats tempStats(List<ActivityRecord> records) {
  final temps = <double>[];
  for (final r in records) {
    if (r.temp != null) temps.add(r.temp!);
  }
  if (temps.isEmpty) {
    return const TempStats(has: false);
  }
  return TempStats(
    has: true,
    min: _round1(temps.reduce(math.min)),
    max: _round1(temps.reduce(math.max)),
    avg: _round1(_avg(temps)),
  );
}

// ---------------- 内部工具 ----------------

double _avg(List<double> xs) => xs.fold<double>(0.0, (a, b) => a + b) / xs.length;

/// 对齐桌面端 `round(v, 1)`（Python 银行家舍入，见 py_round.dart）。
double _round1(double v) => pyRoundTo(v, 1);

/// 对齐桌面端 `round(v)`（Python 银行家舍入）。
double _round0(double v) => pyRound(v).toDouble();

class _RawBucket {
  final int km;
  final double t0;
  double t1;
  final double dist0;
  double dist1;
  final List<double> speeds = [];
  final List<double> hrs = [];
  final List<double> cads = [];
  final List<double> alts = [];

  _RawBucket({
    required this.km,
    required this.t0,
    required this.t1,
    required this.dist0,
    required this.dist1,
  });
}

// ---------------- 结果类型 ----------------

class ZoneTime {
  final int zone;
  final double seconds;
  final double pct;

  /// 区间标签（如 `Z1 < 108bpm(<60%)`）。由 `zones.dart` 填充。
  final String? label;

  const ZoneTime({
    required this.zone,
    required this.seconds,
    required this.pct,
    this.label,
  });
}

class SeriesPoint {
  final double t;
  final double v;
  const SeriesPoint({required this.t, required this.v});
}

class PerKmBucket {
  final int km;
  final double timeS;
  final double? avgSpeedKmh;
  final double? maxSpeedKmh;
  final double? avgHr;
  final double? maxHr;
  final double? avgCad;
  final double? avgAlt;
  const PerKmBucket({
    required this.km,
    required this.timeS,
    this.avgSpeedKmh,
    this.maxSpeedKmh,
    this.avgHr,
    this.maxHr,
    this.avgCad,
    this.avgAlt,
  });
}

class TrackPoint {
  final double lat;
  final double lon;
  final double? altM;
  const TrackPoint({required this.lat, required this.lon, this.altM});
}

class TempStats {
  final bool has;
  final double? min;
  final double? max;
  final double? avg;
  const TempStats({required this.has, this.min, this.max, this.avg});
}
