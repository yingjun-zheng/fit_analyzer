/// 区间定义与标签。
///
/// 移植自 `core/analysis.py` 的 `zone_labels` / `speed_zones` / `hr_zones` /
/// `cadence_zones`。
///
/// ⚠️ 标签文案也要与桌面端一致（虽然是显示层，但两端一致可减少认知差异）。
library;

import '../models/activity_record.dart';
import '../utils/py_round.dart';
import 'analysis.dart';
import 'metrics.dart';

/// 区间边界标签。移植自 `core/analysis.py::zone_labels`。
List<String> zoneLabels(List<double> boundaries, String unit) {
  final labels = <String>[];
  for (var i = 0; i <= boundaries.length; i++) {
    final hasLo = i > 0;
    final hasHi = i < boundaries.length;
    final lo = hasLo ? boundaries[i - 1] : null;
    final hi = hasHi ? boundaries[i] : null;

    if (!hasLo) {
      labels.add('< ${_fmt(hi!)}$unit');
    } else if (!hasHi) {
      labels.add('>= ${_fmt(lo!)}$unit');
    } else {
      labels.add('${_fmt(lo!)}-${_fmt(hi!)}$unit');
    }
  }
  return labels;
}

/// 速度区间（km/h），按时间权重。
///
/// 移植自 `core/analysis.py::speed_zones`。
/// ⚠️ 边界单位是 km/h，但内部要把 record 的 speed_ms 换算后比较
/// —— 桌面端是把边界 /3.6 转成 m/s 再比，这里照做。
List<ZoneTime> speedZones(List<ActivityRecord> records, List<double> boundariesKmh) {
  final b = [for (final x in boundariesKmh) x.toDouble()];
  final mpsBoundaries = [for (final x in b) x / 3.6];
  final zones = weightedZoneTimes(records, (r) => r.speedMs, mpsBoundaries);
  final labels = zoneLabels(b, 'km/h');
  return _withLabels(zones, labels);
}

/// 心率区间（最大心率百分比 5 区）。无心率数据返回 []。
///
/// 移植自 `core/analysis.py::hr_zones`。
List<ZoneTime> hrZones(
  List<ActivityRecord> records, {
  required double? maxHr,
  List<double> pcts = hrZonePcts,
}) {
  if (maxHr == null || maxHr <= 0) return [];
  final b = [for (final p in pcts) maxHr * p];
  final zones = weightedZoneTimes(records, (r) => r.hr, b);

  final labels = <String>[];
  for (var i = 0; i <= b.length; i++) {
    final hasLo = i > 0;
    final hasHi = i < b.length;
    // ⚠️ 桌面端用 Python round()（银行家舍入），必须用 pyRound
    final lo = hasLo ? pyRound(b[i - 1]) : null;
    final hi = hasHi ? pyRound(b[i]) : null;
    final plo = hasLo ? (pcts[i - 1] * 100).toInt() : 0;
    final phi = hasHi ? (pcts[i] * 100).toInt() : 100;

    if (!hasLo) {
      labels.add('Z${i + 1} < ${hi}bpm(<$phi%)');
    } else if (!hasHi) {
      labels.add('Z${i + 1} >= ${lo}bpm($plo%+)');
    } else {
      labels.add('Z${i + 1} $lo-${hi}bpm($plo-$phi%)');
    }
  }
  return _withLabels(zones, labels);
}

/// 踏频区间（rpm）。
///
/// 移植自 `core/analysis.py::cadence_zones`。
List<ZoneTime> cadenceZones(List<ActivityRecord> records, List<double> boundariesRpm) {
  final b = [for (final x in boundariesRpm) x.toDouble()];
  final zones = weightedZoneTimes(records, (r) => r.cad, b);
  final labels = zoneLabels(b, 'rpm');
  return _withLabels(zones, labels);
}

/// 功率区间（瓦）。桌面端 `analysis.py` 未直接提供，按同一套加权逻辑实现。
///
/// 边界通常来自 FTP 百分比（如 55%/75%/90%/105%/120%）。
List<ZoneTime> powerZones(List<ActivityRecord> records, List<double> boundariesW) {
  final b = [for (final x in boundariesW) x.toDouble()];
  final zones = weightedZoneTimes(records, (r) => r.power, b);
  final labels = zoneLabels(b, 'W');
  return _withLabels(zones, labels);
}

/// 按 FTP 百分比生成功率区间边界。
///
/// 常用 Coggan 7 区，但桌面端用 5 区制更常见；这里提供可配置。
List<double> powerBoundariesFromFtp(double ftp, {List<double> pcts = const [0.55, 0.75, 0.90, 1.05]}) {
  return [for (final p in pcts) ftp * p];
}

// ---------------- 内部工具 ----------------

List<ZoneTime> _withLabels(List<ZoneTime> zones, List<String> labels) {
  return [
    for (var i = 0; i < zones.length; i++)
      ZoneTime(
        zone: zones[i].zone,
        seconds: zones[i].seconds,
        pct: zones[i].pct,
        label: i < labels.length ? labels[i] : null,
      ),
  ];
}

/// 数字格式化：整数不带小数点，小数去掉尾随 0。对齐 Python 的 f-string 行为。
String _fmt(double v) {
  if (v == v.roundToDouble()) return v.toInt().toString();
  return v.toString();
}
