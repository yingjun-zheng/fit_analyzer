/// 活动模型。
///
/// 字段对齐 fit_analyzer 桌面端 `core/db.py` 的 `activities` 表，
/// 便于将来导入桌面端数据 / 对照口径。
///
/// ⚠️ 唯一键用 [fileHash]（FIT 文件 SHA1），与桌面端一致 —— 这样同一个
/// FIT 文件无论从哪个平台拉取，都能天然去重。
library;

/// 活动来源平台。
enum ActivitySource {
  igpsport('iGPSPORT'),
  garmin('佳明'),
  garminCn('佳明中国'),
  xingzhe('行者'),
  blackbird('黑鸟单车'),
  magene('迈金'),
  bryton('百锐腾'),
  giant('捷安特'),
  coros('高驰'),
  wahoo('Wahoo'),
  komoot('Komoot'),
  suunto('Suunto'),
  zepp('Zepp'),
  codoon('咕咚'),
  keep('Keep'),
  intervalsIcu('Intervals.icu'),
  outbase('Outbase'),
  localFile('本地文件'),
  unknown('未知');

  final String displayName;
  const ActivitySource(this.displayName);

  static ActivitySource fromName(String? s) {
    if (s == null) return ActivitySource.unknown;
    for (final v in ActivitySource.values) {
      if (v.name == s) return v;
    }
    return ActivitySource.unknown;
  }
}

class Activity {
  /// 数据库自增主键（未入库时为 null）。
  final int? id;

  /// FIT 文件 SHA1 —— **唯一键**。同一个 FIT 文件必得同一 hash。
  final String fileHash;

  final String fileName;
  final String name;

  // ---- 设备 ----
  final String? device;
  final String? deviceBrand;
  final int? product;
  final String? productName;
  final String? hwVersion;
  final String? swVersion;

  // ---- 运动类型 ----
  final String? sport;
  final String? subSportCn;

  // ---- 时间 ----
  /// 本地时间字符串 `YYYY-MM-DD HH:MM:SS`（已含时区偏移）。
  final String startTime;

  /// 起始时间戳（秒，UTC）。
  final int startTs;

  /// 月份 `YYYY-MM`，便于按月查询（冗余字段，同桌面端）。
  final String month;

  // ---- 汇总指标 ----
  final double? totalDistanceM;
  final double? timerS;
  final double? elapsedS;
  final double? movingS;
  final double? avgSpeedMs;
  final double? maxSpeedMs;
  final double? avgHr;
  final double? maxHr;
  final double? minHr;
  final double? avgCad;
  final double? maxCad;
  final double? calories;
  final double? ascentM;
  final double? descentM;
  final double? avgAltM;
  final double? maxAltM;
  final double? minAltM;
  final double? avgTemp;
  final double? maxTemp;
  final double? minTemp;
  final double? lat;
  final double? lon;
  final int? recordCount;

  // ---- 训练负荷 ----
  final double? tss;
  final String? tssMethod;

  // ---- 用户标记 ----
  final bool commute;
  final String vehicle;

  // ---- 元数据 ----
  final String? importedAt;
  final ActivitySource source;

  const Activity({
    this.id,
    required this.fileHash,
    this.fileName = '',
    this.name = '',
    this.device,
    this.deviceBrand,
    this.product,
    this.productName,
    this.hwVersion,
    this.swVersion,
    this.sport,
    this.subSportCn,
    required this.startTime,
    required this.startTs,
    required this.month,
    this.totalDistanceM,
    this.timerS,
    this.elapsedS,
    this.movingS,
    this.avgSpeedMs,
    this.maxSpeedMs,
    this.avgHr,
    this.maxHr,
    this.minHr,
    this.avgCad,
    this.maxCad,
    this.calories,
    this.ascentM,
    this.descentM,
    this.avgAltM,
    this.maxAltM,
    this.minAltM,
    this.avgTemp,
    this.maxTemp,
    this.minTemp,
    this.lat,
    this.lon,
    this.recordCount,
    this.tss,
    this.tssMethod,
    this.commute = false,
    this.vehicle = '',
    this.importedAt,
    this.source = ActivitySource.unknown,
  });

  /// 距离（km），显示用。
  double get distanceKm => (totalDistanceM ?? 0) / 1000.0;

  /// 均速（km/h），显示用。
  double? get avgSpeedKmh => avgSpeedMs != null ? avgSpeedMs! * 3.6 : null;

  /// 计时时长（小时），显示用。
  double get hours => (timerS ?? 0) / 3600.0;

  Map<String, Object?> toMap() => {
        'id': id,
        'file_hash': fileHash,
        'file_name': fileName,
        'name': name,
        'device': device,
        'device_brand': deviceBrand,
        'product': product,
        'product_name': productName,
        'hw_version': hwVersion,
        'sw_version': swVersion,
        'sport': sport,
        'sub_sport_cn': subSportCn,
        'start_time': startTime,
        'start_ts': startTs,
        'month': month,
        'total_distance_m': totalDistanceM,
        'timer_s': timerS,
        'elapsed_s': elapsedS,
        'moving_s': movingS,
        'avg_speed_ms': avgSpeedMs,
        'max_speed_ms': maxSpeedMs,
        'avg_hr': avgHr,
        'max_hr': maxHr,
        'min_hr': minHr,
        'avg_cad': avgCad,
        'max_cad': maxCad,
        'calories': calories,
        'ascent_m': ascentM,
        'descent_m': descentM,
        'avg_alt_m': avgAltM,
        'max_alt_m': maxAltM,
        'min_alt_m': minAltM,
        'avg_temp': avgTemp,
        'max_temp': maxTemp,
        'min_temp': minTemp,
        'lat': lat,
        'lon': lon,
        'record_count': recordCount,
        'tss': tss,
        'tss_method': tssMethod,
        'commute': commute ? 1 : 0,
        'vehicle': vehicle,
        'imported_at': importedAt,
        'source': source.name,
      };

  factory Activity.fromMap(Map<String, Object?> m) => Activity(
        id: m['id'] as int?,
        fileHash: m['file_hash'] as String,
        fileName: (m['file_name'] as String?) ?? '',
        name: (m['name'] as String?) ?? '',
        device: m['device'] as String?,
        deviceBrand: m['device_brand'] as String?,
        product: m['product'] as int?,
        productName: m['product_name'] as String?,
        hwVersion: m['hw_version'] as String?,
        swVersion: m['sw_version'] as String?,
        sport: m['sport'] as String?,
        subSportCn: m['sub_sport_cn'] as String?,
        startTime: (m['start_time'] as String?) ?? '',
        startTs: (m['start_ts'] as int?) ?? 0,
        month: (m['month'] as String?) ?? '',
        totalDistanceM: (m['total_distance_m'] as num?)?.toDouble(),
        timerS: (m['timer_s'] as num?)?.toDouble(),
        elapsedS: (m['elapsed_s'] as num?)?.toDouble(),
        movingS: (m['moving_s'] as num?)?.toDouble(),
        avgSpeedMs: (m['avg_speed_ms'] as num?)?.toDouble(),
        maxSpeedMs: (m['max_speed_ms'] as num?)?.toDouble(),
        avgHr: (m['avg_hr'] as num?)?.toDouble(),
        maxHr: (m['max_hr'] as num?)?.toDouble(),
        minHr: (m['min_hr'] as num?)?.toDouble(),
        avgCad: (m['avg_cad'] as num?)?.toDouble(),
        maxCad: (m['max_cad'] as num?)?.toDouble(),
        calories: (m['calories'] as num?)?.toDouble(),
        ascentM: (m['ascent_m'] as num?)?.toDouble(),
        descentM: (m['descent_m'] as num?)?.toDouble(),
        avgAltM: (m['avg_alt_m'] as num?)?.toDouble(),
        maxAltM: (m['max_alt_m'] as num?)?.toDouble(),
        minAltM: (m['min_alt_m'] as num?)?.toDouble(),
        avgTemp: (m['avg_temp'] as num?)?.toDouble(),
        maxTemp: (m['max_temp'] as num?)?.toDouble(),
        minTemp: (m['min_temp'] as num?)?.toDouble(),
        lat: (m['lat'] as num?)?.toDouble(),
        lon: (m['lon'] as num?)?.toDouble(),
        recordCount: m['record_count'] as int?,
        tss: (m['tss'] as num?)?.toDouble(),
        tssMethod: m['tss_method'] as String?,
        commute: (m['commute'] as num?) == 1,
        vehicle: (m['vehicle'] as String?) ?? '',
        importedAt: m['imported_at'] as String?,
        source: ActivitySource.fromName(m['source'] as String?),
      );

  Activity copyWith({
    int? id,
    String? name,
    double? totalDistanceM,
    double? timerS,
    double? elapsedS,
    double? movingS,
    double? avgSpeedMs,
    double? maxSpeedMs,
    double? avgHr,
    double? maxHr,
    double? minHr,
    double? avgCad,
    double? maxCad,
    double? calories,
    double? ascentM,
    double? descentM,
    double? avgAltM,
    double? maxAltM,
    double? minAltM,
    double? avgTemp,
    double? maxTemp,
    double? minTemp,
    double? lat,
    double? lon,
    int? recordCount,
    double? tss,
    String? tssMethod,
    bool? commute,
    String? vehicle,
    ActivitySource? source,
  }) =>
      Activity(
        id: id ?? this.id,
        fileHash: fileHash,
        fileName: fileName,
        name: name ?? this.name,
        device: device,
        deviceBrand: deviceBrand,
        product: product,
        productName: productName,
        hwVersion: hwVersion,
        swVersion: swVersion,
        sport: sport,
        subSportCn: subSportCn,
        startTime: startTime,
        startTs: startTs,
        month: month,
        totalDistanceM: totalDistanceM ?? this.totalDistanceM,
        timerS: timerS ?? this.timerS,
        elapsedS: elapsedS ?? this.elapsedS,
        movingS: movingS ?? this.movingS,
        avgSpeedMs: avgSpeedMs ?? this.avgSpeedMs,
        maxSpeedMs: maxSpeedMs ?? this.maxSpeedMs,
        avgHr: avgHr ?? this.avgHr,
        maxHr: maxHr ?? this.maxHr,
        minHr: minHr ?? this.minHr,
        avgCad: avgCad ?? this.avgCad,
        maxCad: maxCad ?? this.maxCad,
        calories: calories ?? this.calories,
        ascentM: ascentM ?? this.ascentM,
        descentM: descentM ?? this.descentM,
        avgAltM: avgAltM ?? this.avgAltM,
        maxAltM: maxAltM ?? this.maxAltM,
        minAltM: minAltM ?? this.minAltM,
        avgTemp: avgTemp ?? this.avgTemp,
        maxTemp: maxTemp ?? this.maxTemp,
        minTemp: minTemp ?? this.minTemp,
        lat: lat ?? this.lat,
        lon: lon ?? this.lon,
        recordCount: recordCount ?? this.recordCount,
        tss: tss ?? this.tss,
        tssMethod: tssMethod ?? this.tssMethod,
        commute: commute ?? this.commute,
        vehicle: vehicle ?? this.vehicle,
        importedAt: importedAt,
        source: source ?? this.source,
      );
}
