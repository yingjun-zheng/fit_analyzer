// FIT/GPX/TCX 解析适配层
//
// 职责：把 `activity_files` 的「分离模型」（points + channels）
// 还原成桌面端 `core/fit_parser.py` 的「平铺模型」（List<ActivityRecord>），
// 使 lib/core/stats/ 下的统计算法可以原样工作。
//
// ⚠️ 口径来源：桌面端 core/fit_parser.py::parse_fit_file
//    本文件是它的**忠实移植**，任何偏离都必须在 docs/metrics-contract.md 记录。
//
// 对应关系（桌面 → 移动）：
//   f.get("position_lat")      →  GeoPoint.latitude（已是十进制度）
//   f.get("distance")          →  Channel.distance（metres）
//   f.get("enhanced_speed") ?? f.get("speed")  →  Channel.speed（m/s）
//   f.get("enhanced_altitude") ?? f.get("altitude")  →  GeoPoint.elevation
//   f.get("heart_rate")        →  Channel.heartRate
//   f.get("cadence")           →  Channel.cadence
//   f.get("temperature")       →  Channel.temperature
//   f.get("power")             →  Channel.power

import 'dart:math' as math;
import 'dart:typed_data';

import 'package:activity_files/activity_files.dart' as af;
import 'package:crypto/crypto.dart';

import '../models/activity.dart';
import '../models/activity_record.dart';
import '../utils/py_round.dart';
import 'fit_enums.dart';
import 'fit_supplement.dart';

/// 解析结果：适配层产物 + 解析诊断信息。
class ParsedActivity {
  ParsedActivity({
    required this.fileHash,
    required this.fileName,
    required this.format,
    required this.startTime,
    required this.startTimeLocal,
    required this.records,
    required this.source,
    this.sport,
    this.subSport,
    this.creator,
    this.utcOffsetSeconds = 0,
    this.distanceM,
    this.elapsedSeconds,
    this.timerSeconds,
    this.diagnostics = const <String>[],
  });

  /// sha1(content)，与桌面端一致，用于去重（activities.file_hash UNIQUE）
  final String fileHash;
  final String fileName;

  /// 源文件格式：fit / gpx / tcx / csv / geojson
  final String format;

  /// 活动开始时间（UTC）
  final DateTime startTime;

  /// 活动开始时间（本地，= startTime + utcOffsetSeconds）
  final DateTime startTimeLocal;

  final List<ActivityRecord> records;

  /// 数据来源（本地文件 / 后续的 iGPSPORT、Garmin 等）
  final ActivitySource source;

  final String? sport;
  final String? subSport;
  final String? creator;

  /// 本地时区偏移（秒），由 FIT activity.local_timestamp - timestamp 推算
  final int utcOffsetSeconds;

  /// 汇总距离（米）——仅用于交叉校验，不用作统计口径
  final double? distanceM;

  /// 汇总总耗时（秒）——仅用于交叉校验
  final int? elapsedSeconds;

  /// 汇总计时时间（秒）
  final int? timerSeconds;

  /// 适配层诊断（缺失字段、时间轴退化等），用于排错
  final List<String> diagnostics;

  /// 转成可入库的 Activity。
  ///
  /// 传入 [summarize] 可注入统计汇总逻辑（见 [ActivitySummaryBuilder]），
  /// 避免本文件反向依赖 stats 层。
  Activity toActivity({ActivitySummaryBuilder? summarize}) {
    final sd = startTimeLocal;
    final month =
        '${sd.year.toString().padLeft(4, '0')}-${sd.month.toString().padLeft(2, '0')}';
    final startTimeStr = '${sd.year.toString().padLeft(4, '0')}-'
        '${sd.month.toString().padLeft(2, '0')}-'
        '${sd.day.toString().padLeft(2, '0')} '
        '${sd.hour.toString().padLeft(2, '0')}:'
        '${sd.minute.toString().padLeft(2, '0')}:'
        '${sd.second.toString().padLeft(2, '0')}';

    final base = Activity(
      fileHash: fileHash,
      fileName: fileName,
      name: fileName,
      device: creator,
      sport: sport ?? 'cycling',
      subSportCn: subSport,
      startTime: startTimeStr,
      startTs: startTime.millisecondsSinceEpoch ~/ 1000,
      month: month,
      totalDistanceM: records.isNotEmpty
          ? (records.last.distM ?? distanceM)
          : distanceM,
      elapsedS: (elapsedSeconds ?? 0).toDouble(),
      timerS: timerSeconds?.toDouble(),
      recordCount: records.length,
      importedAt: DateTime.now().toIso8601String(),
      source: source,
    );

    return summarize == null ? base : summarize(base, records);
  }
}

/// 汇总回调签名：给定基础 Activity 与 records，返回补全指标的 Activity。
///
/// 由 stats 层实现（见 `lib/core/stats/summarize.dart`），
/// 让 fit 层不直接依赖统计算法，保持单向依赖。
typedef ActivitySummaryBuilder = Activity Function(
  Activity base,
  List<ActivityRecord> records,
);

/// 解析异常（对应桌面端 FitParseError）
class ActivityParseException implements Exception {
  ActivityParseException(this.message);
  final String message;
  @override
  String toString() => 'ActivityParseException: $message';
}

/// 各 channel 的取值容差。
///
/// 桌面端不存在这个问题（record 自带全部字段），移动端因为 points/channels
/// 分离，需要按时间就近取值。取 2 秒：既容忍轻微采样偏移，
/// 又不会把「停车 30 秒」的数据错误地接上去。
const Duration kChannelTolerance = Duration(seconds: 2);

/// 从字节流解析活动文件（自动识别格式）。
///
/// [source] 标记数据来源；本地导入用 [ActivitySource.localFile]。
ParsedActivity parseActivityBytes(
  Uint8List bytes, {
  required String fileName,
  ActivitySource source = ActivitySource.localFile,
}) {
  final fileHash = sha1.convert(bytes).toString();

  final format = _detectFormat(fileName, bytes);
  if (format == null) {
    throw ActivityParseException('无法识别文件格式: $fileName');
  }

  final af.ActivityParseResult result;
  try {
    result = af.ActivityParser.parseBytes(bytes, format);
  } catch (e) {
    throw ActivityParseException('$fileName 解析失败: $e');
  }

  // FIT 专属补充：activity_files 丢弃了 local_timestamp 与 session.start_time，
  // 而桌面端口径依赖它们（时区偏移、活动起点）。非 FIT 文件跳过。
  final supplement = format == af.ActivityFileFormat.fit
      ? readFitSupplement(bytes)
      : const FitSupplement();

  return _adapt(
    result,
    fileHash: fileHash,
    fileName: fileName,
    source: source,
    formatName: format.name,
    supplement: supplement,
  );
}

/// 文件扩展名 → activity_files 格式枚举
af.ActivityFileFormat? _detectFormat(String fileName, Uint8List bytes) {
  final dot = fileName.lastIndexOf('.');
  final ext = dot >= 0 ? fileName.substring(dot + 1).toLowerCase() : '';
  switch (ext) {
    case 'fit':
      return af.ActivityFileFormat.fit;
    case 'gpx':
      return af.ActivityFileFormat.gpx;
    case 'tcx':
      return af.ActivityFileFormat.tcx;
    case 'csv':
      return af.ActivityFileFormat.csv;
    case 'geojson':
    case 'json':
      return af.ActivityFileFormat.geojson;
  }
  // 扩展名不认识时按魔数嗅探 FIT（前 8 字节 +12 字节 ".FIT"）
  if (bytes.length > 12 &&
      bytes[8] == 0x2E &&
      bytes[9] == 0x46 &&
      bytes[10] == 0x49 &&
      bytes[11] == 0x54) {
    return af.ActivityFileFormat.fit;
  }
  return null;
}

/// 核心：分离模型 → 平铺模型
ParsedActivity _adapt(
  af.ActivityParseResult result, {
  required String fileHash,
  required String fileName,
  required ActivitySource source,
  required String formatName,
  FitSupplement supplement = const FitSupplement(),
}) {
  final raw = result.activity;
  final diagnostics = <String>[];
  for (final d in result.diagnostics) {
    // 只保留 warning 及以上，info 级噪音太多
    if (d.severity != af.ParseSeverity.info) {
      diagnostics.add('[${d.code}] ${d.message}');
    }
  }

  // ---- 时间轴主干：优先 points，退化到 channels 时间并集 ----
  final points = raw.points;
  final channels = raw.channels;

  final timeline = <DateTime>[];
  if (points.isNotEmpty) {
    for (final p in points) {
      timeline.add(p.time);
    }
  } else {
    // 无 GPS：用所有 channel 时间戳的并集，排序去重
    final set = <int, DateTime>{};
    for (final samples in channels.values) {
      for (final s in samples) {
        set[s.time.microsecondsSinceEpoch] = s.time;
      }
    }
    if (set.isEmpty) {
      throw ActivityParseException('$fileName 没有可用的时间序列数据');
    }
    timeline.addAll(set.values);
    timeline.sort();
    diagnostics.add('无 GPS 点，时间轴退化为传感器时间并集（${timeline.length} 点）');
  }

  if (timeline.isEmpty) {
    throw ActivityParseException('$fileName 没有逐条记录数据');
  }

  // ---- 起点时间：session.start_time 优先，否则时间轴首点 ----
  // 完全对齐桌面端 core/fit_parser.py:149-158：
  //   start_dt = session["start_time"]  →  否则 records[0].timestamp
  // activity_files 的 ActivitySummary 不含 start_time（其 FIT 解析器丢弃了字段 2），
  // 因此用 fit_supplement 从原始字节补齐。
  final startTime = supplement.sessionStartTime ?? timeline.first;
  final startMicros = startTime.toUtc().microsecondsSinceEpoch;

  // ---- 时区偏移（桌面端 fit_parser.py:160-170）----
  final utcOffsetSeconds = supplement.utcOffsetSeconds;
  if (supplement.localTimestamp == null)
    diagnostics.add('未取到 activity.local_timestamp，时区偏移按 0 处理');

  // ---- 逐点 join ----
  final cursor = af.ChannelMapper.cursor(channels, maxDelta: kChannelTolerance);
  final out = <ActivityRecord>[];
  double? prevDist;
  double? prevSpeed;
  double? prevT;

  for (var i = 0; i < timeline.length; i++) {
    final time = timeline[i];
    final t = math.max(
      0.0,
      (time.toUtc().microsecondsSinceEpoch - startMicros) / 1000000.0,
    );

    double? lat;
    double? lon;
    double? alt;
    if (i < points.length) {
      final p = points[i];
      lat = p.latitude;
      lon = p.longitude;
      alt = p.elevation;
    }

    final snap = cursor.snapshot(time);
    var dist = snap.valueFor(af.Channel.distance);
    var speed = snap.valueFor(af.Channel.speed);
    final hr = snap.valueFor(af.Channel.heartRate);
    final cad = snap.valueFor(af.Channel.cadence);
    final temp = snap.valueFor(af.Channel.temperature);
    final power = snap.valueFor(af.Channel.power);

    // 缺失速度时用距离差推导（桌面端 fit_parser.py:196）
    if (speed == null &&
        prevDist != null &&
        dist != null &&
        prevT != null &&
        t > prevT) {
      speed = math.max(0.0, dist - prevDist) / (t - prevT);
    }
    speed ??= 0.0;

    out.add(ActivityRecord(
      t: _round(t, 1),
      lat: lat == null ? null : _round(lat, 7),
      lon: lon == null ? null : _round(lon, 7),
      distM: dist == null ? null : _round(dist, 1),
      speedMs: _round(speed, 3),
      hr: hr == null ? null : _round(hr, 0),
      cad: cad == null ? null : _round(cad, 0),
      altM: alt == null ? null : _round(alt, 1),
      temp: temp == null ? null : _round(temp, 1),
      power: power == null ? null : _round(power, 0),
    ));

    prevDist = dist;
    prevT = t;
  }

  // ---- 距离缺失时用速度积分补全（桌面端 fit_parser.py:219） ----
  var lastDist = 0.0;
  for (var i = 0; i < out.length; i++) {
    final r = out[i];
    if (r.distM == null) {
      if (i > 0) {
        final dt = r.t - out[i - 1].t;
        lastDist += (r.speedMs ?? 0.0) * dt;
      }
      out[i] = r.copyWith(distM: _round(lastDist, 1));
    } else {
      lastDist = r.distM!;
    }
  }

  // ---- 汇总字段（仅供交叉校验） ----
  final summary = raw.summary;
  final distanceM = summary?.totalDistanceMeters ??
      (out.isNotEmpty ? out.last.distM : null);
  final elapsedSeconds =
      summary?.elapsedTime?.inSeconds ?? pyRound(out.last.t);
  final timerSeconds = summary?.timerTime?.inSeconds;

  return ParsedActivity(
    fileHash: fileHash,
    fileName: fileName,
    format: formatName,
    startTime: startTime.toUtc(),
    startTimeLocal: startTime.toUtc().add(Duration(seconds: utcOffsetSeconds)),
    records: out,
    source: source,
    sport: _sportName(raw, supplement),
    subSport: _subSportName(raw),
    creator: _creatorName(raw),
    utcOffsetSeconds: utcOffsetSeconds,
    distanceM: distanceM,
    elapsedSeconds: elapsedSeconds,
    timerSeconds: timerSeconds,
    diagnostics: diagnostics,
  );
}

/// sport：优先 session.sport（多会话文件），否则 activity.sport。
///
/// activity_files 给的是 [af.Sport] 枚举，桌面端给的是 fitparse 字符串；
/// 这里映射回字符串名，保证与桌面端 `sport` 字段逐字一致。
String? _sportName(af.RawActivity raw, FitSupplement supplement) {
  final s = raw.summary?.sport ?? raw.sport;
  final name = s.name;
  return name == 'unknown' ? null : name;
}

/// sub_sport：activity_files 给 FIT 枚举数值，桌面端给字符串名。
/// 用 [fitSubSportName] 还原成字符串，供上层套用中文表。
String? _subSportName(af.RawActivity raw) =>
    fitSubSportName(raw.summary?.subSport);

/// 设备名：桌面端 `_format_device(manufacturer, product, product_name, ...)`。
///
/// 对齐策略：厂商 + 型号名（有则用），否则退回厂商名。
/// 单独校验：activity_files 的 [af.ActivityDeviceMetadata] 只有
/// manufacturer / model / product / softwareVersion，没有 productName。
String? _creatorName(af.RawActivity raw) {
  final device = raw.device;
  final creator = raw.creator;
  final mc = device?.manufacturer;
  final model = device?.model;
  if (mc != null && model != null && model.isNotEmpty) return '$mc $model';
  if (mc != null && mc.isNotEmpty) return mc;
  if (creator != null && creator.trim().isNotEmpty) return creator.trim();
  return null;
}

/// 按桌面端口径舍入：`round(v, digits)`。
///
/// 桌面端 fit_parser.py 全用 Python round()（银行家舍入），见 [pyRound]。
double _round(double value, int digits) => pyRoundTo(value, digits);
