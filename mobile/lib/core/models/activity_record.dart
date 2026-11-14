/// 逐条记录（record）模型。
///
/// 对应 fit_analyzer 桌面端 `core/fit_parser.py` 输出的 `records` 数组元素。
/// 字段名与桌面端保持一致，便于对照与测试。
///
/// ⚠️ 注意：FIT 文件原始数据中 GPS 点与传感器通道是**分开**的
/// （见 `lib/core/fit/README.md`）。本模型是**按时间戳 join 之后**的统一视图，
/// 与桌面端的平铺结构一致。
library;

class ActivityRecord {
  /// 相对活动开始的秒数。
  final double t;

  final double? lat;
  final double? lon;

  /// 累计距离（米）。
  final double? distM;

  /// 瞬时速度（米/秒）。
  final double? speedMs;

  /// 心率（bpm）。
  final double? hr;

  /// 踏频（rpm）。
  final double? cad;

  /// 海拔（米）。
  final double? altM;

  /// 温度（摄氏度）。
  final double? temp;

  /// 功率（瓦）。
  final double? power;

  /// 是否为估算功率（非真实功率计数据）。
  ///
  /// ⚠️ 估算功率**不得用于 TSS 计算**（误差过大），这一点与桌面端一致
  /// （见 `core/training_load.py` 的 `compute_activity_tss`）。
  final bool powerEstimated;

  const ActivityRecord({
    required this.t,
    this.lat,
    this.lon,
    this.distM,
    this.speedMs,
    this.hr,
    this.cad,
    this.altM,
    this.temp,
    this.power,
    this.powerEstimated = false,
  });

  ActivityRecord copyWith({
    double? t,
    double? lat,
    double? lon,
    double? distM,
    double? speedMs,
    double? hr,
    double? cad,
    double? altM,
    double? temp,
    double? power,
    bool? powerEstimated,
  }) =>
      ActivityRecord(
        t: t ?? this.t,
        lat: lat ?? this.lat,
        lon: lon ?? this.lon,
        distM: distM ?? this.distM,
        speedMs: speedMs ?? this.speedMs,
        hr: hr ?? this.hr,
        cad: cad ?? this.cad,
        altM: altM ?? this.altM,
        temp: temp ?? this.temp,
        power: power ?? this.power,
        powerEstimated: powerEstimated ?? this.powerEstimated,
      );

  /// 转为 Map（用于数据库读写）。
  Map<String, Object?> toMap() => {
        't': t,
        'lat': lat,
        'lon': lon,
        'dist_m': distM,
        'speed_ms': speedMs,
        'hr': hr,
        'cad': cad,
        'alt_m': altM,
        'temp': temp,
        'power': power,
        'power_estimated': powerEstimated ? 1 : 0,
      };

  /// 从 Map 构造。注意桌面端存的是 snake_case。
  factory ActivityRecord.fromMap(Map<String, Object?> m) => ActivityRecord(
        t: (m['t'] as num).toDouble(),
        lat: (m['lat'] as num?)?.toDouble(),
        lon: (m['lon'] as num?)?.toDouble(),
        distM: (m['dist_m'] as num?)?.toDouble(),
        speedMs: (m['speed_ms'] as num?)?.toDouble(),
        hr: (m['hr'] as num?)?.toDouble(),
        cad: (m['cad'] as num?)?.toDouble(),
        altM: (m['alt_m'] as num?)?.toDouble(),
        temp: (m['temp'] as num?)?.toDouble(),
        power: (m['power'] as num?)?.toDouble(),
        powerEstimated: (m['power_estimated'] as num?) == 1,
      );
}
