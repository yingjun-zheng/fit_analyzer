/// 月度 / 年度统计口径。
///
/// 移植自 `core/month_agent.py` 的 `_month_overview` / `_month_distance_trend` /
/// `_month_hr_summary` / `_month_speed_summary`。
///
/// ⚠️ 特别注意「平均速度」的歧义：桌面端同时提供
///   - `avg_speed_kmh`        —— 各活动均速的**算术平均**
///   - `weighted_avg_speed_kmh` —— **按里程加权**（Σ(均速×距离)/Σ距离）
/// 这是两个不同的数字，UI 必须明确标注用的是哪个。
library;

import '../models/activity.dart';
import '../utils/py_round.dart';

/// 月度概览。逐字对齐 `core/month_agent.py::_month_overview`。
MonthOverview monthOverview(List<Activity> activities) {
  if (activities.isEmpty) {
    return const MonthOverview.empty();
  }

  var totalDist = 0.0;
  var totalTime = 0.0;
  var totalAscent = 0.0;
  var totalCal = 0.0;
  var commuteDist = 0.0;
  var commuteCnt = 0;
  final speeds = <double>[];

  for (final a in activities) {
    totalDist += a.totalDistanceM ?? 0;
    totalTime += a.timerS ?? 0;
    totalAscent += a.ascentM ?? 0;
    totalCal += a.calories ?? 0;
    if (a.avgSpeedMs != null && a.avgSpeedMs! != 0) speeds.add(a.avgSpeedMs!);
    if (a.commute) {
      commuteDist += a.totalDistanceM ?? 0;
      commuteCnt += 1;
    }
  }

  // 加权平均速度：Σ(均速 × 距离) / Σ距离
  double? weightedSpeed;
  if (totalDist > 0) {
    var acc = 0.0;
    for (final a in activities) {
      acc += (a.avgSpeedMs ?? 0) * (a.totalDistanceM ?? 0);
    }
    weightedSpeed = acc / totalDist * 3.6;
  }

  return MonthOverview(
    count: activities.length,
    distanceKm: _round1(totalDist / 1000),
    hours: _round1(totalTime / 3600),
    ascentM: _round0(totalAscent),
    calories: _round0(totalCal),
    avgSpeedKmh: speeds.isNotEmpty ? _round1(_safeAvg([for (final s in speeds) s * 3.6])) : null,
    weightedAvgSpeedKmh: weightedSpeed != null ? _round1(weightedSpeed) : null,
    commuteCount: commuteCnt,
    commuteDistanceKm: _round1(commuteDist / 1000),
    trainingDistanceKm: _round1((totalDist - commuteDist) / 1000),
  );
}

/// 月度按天距离趋势。对齐 `core/month_agent.py::_month_distance_trend`。
MonthTrend monthDistanceTrend(List<Activity> activities) {
  final days = <String, ({double distanceKm, int count})>{};

  for (final a in activities) {
    final d = a.startTime.length >= 10 ? a.startTime.substring(0, 10) : a.startTime;
    if (d.isEmpty) continue;
    final prev = days[d];
    days[d] = (
      distanceKm: (prev?.distanceKm ?? 0) + (a.totalDistanceM ?? 0) / 1000.0,
      count: (prev?.count ?? 0) + 1,
    );
  }

  final keys = days.keys.toList()..sort();
  final trend = [
    for (final d in keys)
      DayTrend(
        date: d,
        distanceKm: _round1(days[d]!.distanceKm),
        count: days[d]!.count,
      ),
  ];

  final distances = [for (final t in trend) t.distanceKm];
  return MonthTrend(
    dayCount: trend.length,
    maxDailyDistanceKm: distances.isNotEmpty ? _round1(distances.reduce((a, b) => a > b ? a : b)) : null,
    minDailyDistanceKm: distances.isNotEmpty ? _round1(distances.reduce((a, b) => a < b ? a : b)) : null,
    trend: trend,
  );
}

/// 月度心率聚合。对齐 `core/month_agent.py::_month_hr_summary`。
MonthHrSummary monthHrSummary(List<Activity> activities) {
  final hrs = <double>[];
  final maxHrs = <double>[];
  for (final a in activities) {
    if (a.avgHr != null && a.avgHr! != 0) hrs.add(a.avgHr!);
    if (a.maxHr != null && a.maxHr! != 0) maxHrs.add(a.maxHr!);
  }
  if (hrs.isEmpty) {
    return const MonthHrSummary(hasData: false);
  }
  return MonthHrSummary(
    hasData: true,
    activitiesWithHr: hrs.length,
    avgHrMean: _round0(_safeAvg(hrs)),
    maxHrMax: maxHrs.isNotEmpty
        ? _round0(maxHrs.reduce((a, b) => a > b ? a : b))
        : null,
  );
}

/// 多月份趋势（近 N 个月）。
///
/// 桌面端 month_agent 没有这个图，是移动端新增的。但**每月的口径
/// 仍然用 [monthOverview]**，保证与单月页面一致。
List<MonthPoint> monthlyTrend(List<Activity> all, {int months = 12}) {
  final byMonth = <String, List<Activity>>{};
  for (final a in all) {
    final m = a.month;
    if (m.isEmpty) continue;
    byMonth.putIfAbsent(m, () => []).add(a);
  }

  final keys = byMonth.keys.toList()..sort();
  final recent = keys.length > months ? keys.sublist(keys.length - months) : keys;

  return [
    for (final m in recent)
      MonthPoint(
        month: m,
        distanceKm: _round1(
          byMonth[m]!.fold<double>(0, (s, a) => s + (a.totalDistanceM ?? 0)) / 1000,
        ),
        hours: _round1(
          byMonth[m]!.fold<double>(0, (s, a) => s + (a.timerS ?? 0)) / 3600,
        ),
        ascentM: _round0(
          byMonth[m]!.fold<double>(0, (s, a) => s + (a.ascentM ?? 0)),
        ),
        count: byMonth[m]!.length,
      ),
  ];
}

/// 个人纪录（PR）。桌面端 `fitness.py` 的简化对应。
PersonalRecords personalRecords(List<Activity> activities) {
  Activity? longest;
  Activity? biggestClimb;
  Activity? fastest;

  for (final a in activities) {
    if (a.totalDistanceM != null &&
        (longest == null || a.totalDistanceM! > (longest.totalDistanceM ?? 0))) {
      longest = a;
    }
    if (a.ascentM != null && (biggestClimb == null || a.ascentM! > (biggestClimb.ascentM ?? 0))) {
      biggestClimb = a;
    }
    // 最快均速：排除过短活动（<5km）避免异常值
    if (a.avgSpeedMs != null && (a.totalDistanceM ?? 0) >= 5000) {
      if (fastest == null || a.avgSpeedMs! > (fastest.avgSpeedMs ?? 0)) {
        fastest = a;
      }
    }
  }

  return PersonalRecords(
    longestRide: longest,
    biggestClimb: biggestClimb,
    fastestRide: fastest,
  );
}

/// 年度统计：复用 [monthOverview] 的口径，避免两套算法漂移。
YearOverview yearOverview(List<Activity> activities) {
  final months = monthlyTrend(activities, months: 12);
  final overview = monthOverview(activities);
  return YearOverview(overview: overview, months: months);
}

// ---------------- 内部工具 ----------------

double _safeAvg(List<double> xs) {
  if (xs.isEmpty) return 0.0;
  return xs.fold<double>(0.0, (a, b) => a + b) / xs.length;
}

/// 对齐桌面端 `round(v, 1)`（Python 银行家舍入）。
double _round1(double v) => pyRoundTo(v, 1);

/// 对齐桌面端 `round(v)`（Python 银行家舍入）。
double _round0(double v) => pyRound(v).toDouble();

// ---------------- 结果类型 ----------------

class MonthOverview {
  final int count;
  final double distanceKm;
  final double hours;
  final double ascentM;
  final double calories;

  /// 各活动均速的**算术平均**（仅含有均速的活动）。
  final double? avgSpeedKmh;

  /// **按里程加权**的平均速度：Σ(均速×距离)/Σ距离。
  ///
  /// ⚠️ 与 [avgSpeedKmh] 是两个不同数字。UI 推荐主显这个（更符合骑行者直觉），
  /// 但必须标注清楚。
  final double? weightedAvgSpeedKmh;

  final int commuteCount;
  final double commuteDistanceKm;
  final double trainingDistanceKm;

  const MonthOverview({
    required this.count,
    required this.distanceKm,
    required this.hours,
    required this.ascentM,
    required this.calories,
    this.avgSpeedKmh,
    this.weightedAvgSpeedKmh,
    this.commuteCount = 0,
    this.commuteDistanceKm = 0,
    this.trainingDistanceKm = 0,
  });

  const MonthOverview.empty()
      : count = 0,
        distanceKm = 0,
        hours = 0,
        ascentM = 0,
        calories = 0,
        avgSpeedKmh = null,
        weightedAvgSpeedKmh = null,
        commuteCount = 0,
        commuteDistanceKm = 0,
        trainingDistanceKm = 0;
}

class DayTrend {
  final String date;
  final double distanceKm;
  final int count;
  const DayTrend({required this.date, required this.distanceKm, required this.count});
}

class MonthTrend {
  final int dayCount;
  final double? maxDailyDistanceKm;
  final double? minDailyDistanceKm;
  final List<DayTrend> trend;
  const MonthTrend({
    required this.dayCount,
    this.maxDailyDistanceKm,
    this.minDailyDistanceKm,
    this.trend = const [],
  });
}

class MonthHrSummary {
  final bool hasData;
  final int activitiesWithHr;
  final double? avgHrMean;
  final double? maxHrMax;
  const MonthHrSummary({
    required this.hasData,
    this.activitiesWithHr = 0,
    this.avgHrMean,
    this.maxHrMax,
  });
}

class MonthPoint {
  final String month;
  final double distanceKm;
  final double hours;
  final double ascentM;
  final int count;
  const MonthPoint({
    required this.month,
    required this.distanceKm,
    required this.hours,
    required this.ascentM,
    required this.count,
  });
}

class PersonalRecords {
  final Activity? longestRide;
  final Activity? biggestClimb;
  final Activity? fastestRide;
  const PersonalRecords({this.longestRide, this.biggestClimb, this.fastestRide});
}

class YearOverview {
  final MonthOverview overview;
  final List<MonthPoint> months;
  const YearOverview({required this.overview, required this.months});
}
