/// 汇总指标构建：把 records 聚合成 Activity 的汇总字段。
///
/// 移植自 `core/fit_parser.py::parse_fit_file` 的 `summary` 段（第 229–422 行）。
///
/// ⚠️ **核心口径：优先信会话（session）汇总值，缺失时才从 records 自算。**
///
/// 这与 `docs/metrics-contract.md` 开头「为什么必须自己算」并不矛盾 ——
/// 那里说的是**爬升/移动时间这类厂商算法差异大的字段不能用 FIT 自带值**；
/// 而桌面端的实际做法是分层：
///
/// | 字段 | 桌面端策略 |
/// |---|---|
/// | `total_distance` | 会话值 → 无则用末条 `dist_m` |
/// | `timer_s` | `total_timer_time` → 无则 `total_moving_time` → 无则末条 `t` |
/// | `elapsed_s` | `total_elapsed_time`（无兜底） |
/// | `moving_s` | `total_moving_time`（**无兜底**，可能为 null） |
/// | `avg_speed_ms` | `enhanced_avg_speed`/`avg_speed` → 无则 `total_dist / timer` |
/// | `max_speed_ms` | `enhanced_max_speed`/`max_speed`（无兜底） |
/// | `avg_hr` / `max_hr` / `min_hr` | 会话值 → 无则对 records 算术平均 |
/// | `avg_cad` / `max_cad` | 会话值 → 无则对 records 算术平均 |
/// | `ascent_m` / `descent_m` | 会话值 → 无则 [accumulateAscentDescent] |
/// | `avg_alt_m` / `max_alt_m` / `min_alt_m` | 会话值 → 无则对 records 算术平均 |
/// | `avg_temp` / `max_temp` / `min_temp` | 会话值 → 无则对 records 算术平均 |
/// | `lat` / `lon` | 会话起点 → 无则第一个有 GPS 的 record |
///
/// 平均值一律**算术平均**（`sum(vals)/len(vals)`），不是时间加权。
///
/// ⚠️ `activity_files` 的 `ActivitySummary` 字段覆盖度不如 fitparse 的 session
/// message（例如无 `min_*`、无 `total_ascent`）。因此移动端实际会更频繁地走
/// 「自算」分支 —— 这会在与桌面端比对时产生差异，属于**已知的模型差异**，
/// 需在 `lib/core/fit/README.md` 的落地清单里实测确认哪些字段能对齐。
library;

import 'dart:math' as math;

import '../models/activity.dart';
import '../models/activity_record.dart';
import '../utils/py_round.dart';
import 'analysis.dart';

/// 中文 sub_sport 映射（照抄桌面端 fit_parser.py:320）。
const Map<String, String> subSportCnMap = {
  'generic': '通用',
  'road': '公路骑行',
  'mountain': '山地骑行',
  'gravel': '砾石骑行',
  'cyclocross': '公路越野',
  'commuting': '通勤',
  'touring': '长途骑行',
  'track': '场地骑行',
  'indoor_cycling': '室内骑行',
  'virtual_ride': '虚拟骑行',
  'e_bike': '电助力',
};

/// 从 records 计算全部汇总指标，填充到 [base]。
///
/// 这是 [ActivitySummaryBuilder] 的实现，注入给
/// `parseActivityBytes(...).toActivity(summarize: buildActivitySummary)`。
Activity buildActivitySummary(Activity base, List<ActivityRecord> records) {
  if (records.isEmpty) return base;

  // ---- 距离：会话值 → 末条 dist_m（桌面端 239–241） ----
  final totalDist = base.totalDistanceM ?? records.last.distM ?? 0.0;

  // ---- 计时：timer → moving → 末条 t（桌面端 242–244） ----
  final timer = base.timerS ?? base.movingS ?? records.last.t;

  // ---- 均速：会话值 → total_dist / timer（桌面端 247–249） ----
  final avgSpeed = base.avgSpeedMs ??
      (timer > 0 && totalDist > 0 ? totalDist / timer : null);

  // ---- 最大速度：会话值（无兜底，桌面端 401） ----
  final maxSpeed = base.maxSpeedMs;

  // ---- 心率：会话值 → 算术平均（桌面端 259–267） ----
  final hrVals = _values(records, (r) => r.hr);
  var avgHr = base.avgHr ?? (hrVals.isEmpty ? null : _avg(hrVals));
  var maxHr = base.maxHr ?? (hrVals.isEmpty ? null : hrVals.reduce(math.max));
  var minHr = base.minHr ?? (hrVals.isEmpty ? null : hrVals.reduce(math.min));

  // ---- 踏频：会话值 → 算术平均（桌面端 269–275） ----
  final cadVals = _values(records, (r) => r.cad);
  final avgCad = base.avgCad ?? (cadVals.isEmpty ? null : _avg(cadVals));
  final maxCad =
      base.maxCad ?? (cadVals.isEmpty ? null : cadVals.reduce(math.max));

  // ---- 爬升/下降：会话值 → 滞回累计（桌面端 278–286） ----
  final ad = accumulateAscentDescent([for (final r in records) r.altM]);
  final ascent = base.ascentM ?? ad.ascent;
  final descent = base.descentM ?? ad.descent;

  // ---- 海拔：会话值 → 算术平均（桌面端 288–296） ----
  final altVals = _values(records, (r) => r.altM);
  final avgAlt = base.avgAltM ?? (altVals.isEmpty ? null : _avg(altVals));
  final maxAlt =
      base.maxAltM ?? (altVals.isEmpty ? null : altVals.reduce(math.max));
  final minAlt =
      base.minAltM ?? (altVals.isEmpty ? null : altVals.reduce(math.min));

  // ---- 温度：会话值 → 算术平均（桌面端 298–306） ----
  final tempVals = _values(records, (r) => r.temp);
  final avgTemp = base.avgTemp ?? (tempVals.isEmpty ? null : _avg(tempVals));
  final maxTemp =
      base.maxTemp ?? (tempVals.isEmpty ? null : tempVals.reduce(math.max));
  final minTemp =
      base.minTemp ?? (tempVals.isEmpty ? null : tempVals.reduce(math.min));

  // ---- 起点经纬度：会话值 → 第一个有 GPS 的点（桌面端 308–314） ----
  double? lat = base.lat;
  double? lon = base.lon;
  if (lat == null || lon == null) {
    for (final r in records) {
      if (r.lat != null && r.lon != null) {
        lat = r.lat;
        lon = r.lon;
        break;
      }
    }
  }

  // ---- 移动时间：会话值，**无兜底**（桌面端 246） ----
  // 注意：桌面端不会用自算的 movingTime 填充这个字段。
  // 若 FIT 没有 total_moving_time，桌面端此处就是 null。
  final moving = base.movingS;

  return base.copyWith(
    totalDistanceM: pyRoundTo(totalDist, 1),
    timerS: pyRoundTo(timer, 1),
    movingS: moving == null ? null : pyRoundTo(moving, 1),
    avgSpeedMs: avgSpeed == null ? null : pyRoundTo(avgSpeed, 3),
    maxSpeedMs: maxSpeed == null ? null : pyRoundTo(maxSpeed, 3),
    avgHr: avgHr == null ? null : pyRound(avgHr).toDouble(),
    maxHr: maxHr == null ? null : pyRound(maxHr).toDouble(),
    minHr: minHr == null ? null : pyRound(minHr).toDouble(),
    avgCad: avgCad == null ? null : pyRound(avgCad).toDouble(),
    maxCad: maxCad == null ? null : pyRound(maxCad).toDouble(),
    ascentM: pyRoundTo(ascent, 1),
    descentM: pyRoundTo(descent, 1),
    avgAltM: avgAlt == null ? null : pyRoundTo(avgAlt, 1),
    maxAltM: maxAlt == null ? null : pyRoundTo(maxAlt, 1),
    minAltM: minAlt == null ? null : pyRoundTo(minAlt, 1),
    avgTemp: avgTemp == null ? null : pyRoundTo(avgTemp, 1),
    maxTemp: maxTemp == null ? null : pyRoundTo(maxTemp, 1),
    minTemp: minTemp == null ? null : pyRoundTo(minTemp, 1),
    lat: lat,
    lon: lon,
    recordCount: records.length,
  );
}

// ---------------- 内部工具 ----------------

List<double> _values(
  List<ActivityRecord> records,
  double? Function(ActivityRecord) getter,
) {
  final out = <double>[];
  for (final r in records) {
    final v = getter(r);
    if (v != null) out.add(v);
  }
  return out;
}

double _avg(List<double> xs) =>
    xs.fold<double>(0.0, (a, b) => a + b) / xs.length;

/// sub_sport 转中文（照抄桌面端逻辑）。
String subSportToCn(String? subSport) {
  if (subSport == null || subSport.isEmpty) return '';
  return subSportCnMap[subSport.toLowerCase()] ?? subSport;
}
