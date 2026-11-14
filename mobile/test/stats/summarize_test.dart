/// 汇总指标构建测试。
///
/// 期望值均由 fit_analyzer 桌面端 `core/fit_parser.py::parse_fit_file`
/// 的 summary 段实际运行得到（见 docs/metrics-contract.md）。
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:fit_analyzer_mobile/core/models/activity.dart';
import 'package:fit_analyzer_mobile/core/models/activity_record.dart';
import 'package:fit_analyzer_mobile/core/stats/analysis.dart';
import 'package:fit_analyzer_mobile/core/stats/summarize.dart';

Activity _base() => const Activity(
      fileHash: 'x',
      startTime: '2026-09-20 08:00:00',
      startTs: 1758326400,
      month: '2026-09',
    );

void main() {
  group('buildActivitySummary', () {
    test('空 records 原样返回', () {
      final a = _base();
      expect(buildActivitySummary(a, const []), same(a));
    });

    test('距离/计时取 records 末值（无会话汇总时）', () {
      final rs = [
        const ActivityRecord(t: 0, distM: 0, speedMs: 5, altM: 100),
        const ActivityRecord(t: 10, distM: 50, speedMs: 5, altM: 100),
        const ActivityRecord(t: 20, distM: 100, speedMs: 5, altM: 101),
      ];
      final a = buildActivitySummary(_base(), rs);
      // 桌面端：total_dist = 末条 dist_m；timer = 末条 t（无 session 时）
      expect(a.totalDistanceM, 100.0);
      expect(a.timerS, 20.0);
      expect(a.recordCount, 3);
    });

    test('★ moving_s 用会话值，无会话则保持 null（桌面端口径）', () {
      // 桌面端 `moving = _num(sget("total_moving_time"))` —— 无兜底。
      // 即便 records 明显在移动，也不自算填充。
      final rs = [
        const ActivityRecord(t: 0, distM: 0, speedMs: 5),
        const ActivityRecord(t: 10, distM: 50, speedMs: 5),
      ];
      final a = buildActivitySummary(_base(), rs);
      expect(a.movingS, isNull);
    });

    test('★ 会话值优先于自算（模拟 FIT session 齐全的情况）', () {
      // 对应实测的 iGPSPORT 文件：timer_s == moving_s == 4312.0
      final base = const Activity(
        fileHash: 'x',
        startTime: '2026-07-05 16:33:49',
        startTs: 1783211629,
        month: '2026-07',
        totalDistanceM: 20536.2,
        timerS: 4312.0,
        elapsedS: 4743.0,
        movingS: 4312.0,
        avgSpeedMs: 4.762,
        maxSpeedMs: 7.986,
        avgCad: 58,
        maxCad: 82,
        ascentM: 31.0,
        descentM: 33.0,
        avgAltM: 68.2,
        maxAltM: 76.0,
        minAltM: 64.0,
        avgTemp: 27.0,
        maxTemp: 29.0,
      );
      final rs = [
        const ActivityRecord(t: 0, distM: 0, speedMs: 3.687, cad: 29, altM: 76.0, temp: 27.0),
        const ActivityRecord(t: 4743, distM: 20536.2, speedMs: 2.555, cad: 32, altM: 67.0, temp: 27.0),
      ];
      final a = buildActivitySummary(base, rs);
      // 全部保留会话值，不被自算覆盖
      expect(a.totalDistanceM, 20536.2);
      expect(a.timerS, 4312.0);
      expect(a.movingS, 4312.0);
      expect(a.avgSpeedMs, 4.762);
      expect(a.maxSpeedMs, 7.986);
      expect(a.avgCad, 58.0);
      expect(a.ascentM, 31.0);
      expect(a.descentM, 33.0);
      // 会话无心率 → 自算（两条都无 hr → null）
      expect(a.avgHr, isNull);
    });

    test('均速 = 距离 / 计时', () {
      final rs = [
        const ActivityRecord(t: 0, distM: 0, speedMs: 5),
        const ActivityRecord(t: 100, distM: 1000, speedMs: 10),
      ];
      final a = buildActivitySummary(_base(), rs);
      // avg = 1000 / 100
      expect(a.avgSpeedMs, closeTo(10.0, 1e-9));
    });

    test('最大/最小/平均心率 —— 算术平均，同桌面端', () {
      final rs = [
        const ActivityRecord(t: 0, hr: 100),
        const ActivityRecord(t: 1, hr: 120),
        const ActivityRecord(t: 2, hr: 140),
      ];
      final a = buildActivitySummary(_base(), rs);
      expect(a.avgHr, closeTo(120.0, 1e-9));
      expect(a.maxHr, 140.0);
      expect(a.minHr, 100.0);
    });

    test('心率含 null 时不参与平均', () {
      final rs = [
        const ActivityRecord(t: 0, hr: 100),
        const ActivityRecord(t: 1),
        const ActivityRecord(t: 2, hr: 160),
      ];
      final a = buildActivitySummary(_base(), rs);
      expect(a.avgHr, closeTo(130.0, 1e-9));
      expect(a.maxHr, 160.0);
    });

    test('爬升/下降走滞回算法（阈值 1.0m）', () {
      // 与 analysis_test 中同一组海拔
      final rs = [
        const ActivityRecord(t: 0, altM: 100.0),
        const ActivityRecord(t: 1, altM: 100.5),
        const ActivityRecord(t: 2, altM: 101.8),
        const ActivityRecord(t: 3, altM: 101.2),
        const ActivityRecord(t: 4, altM: 102.5),
        const ActivityRecord(t: 5, altM: 103.0),
        const ActivityRecord(t: 6, altM: 102.0),
        const ActivityRecord(t: 7, altM: 104.5),
        const ActivityRecord(t: 8, altM: 99.0),
      ];
      final a = buildActivitySummary(_base(), rs);
      expect(a.ascentM, closeTo(5.5, 1e-9));
      expect(a.descentM, closeTo(6.5, 1e-9));
    });

    test('温度统计', () {
      final rs = [
        const ActivityRecord(t: 0, temp: 20.0),
        const ActivityRecord(t: 1, temp: 25.0),
        const ActivityRecord(t: 2, temp: 30.0),
      ];
      final a = buildActivitySummary(_base(), rs);
      expect(a.avgTemp, closeTo(25.0, 1e-9));
      expect(a.maxTemp, 30.0);
      expect(a.minTemp, 20.0);
    });

    test('起点经纬度取第一个有 GPS 的点', () {
      final rs = [
        const ActivityRecord(t: 0),
        const ActivityRecord(t: 1, lat: 30.1234567, lon: 120.7654321),
        const ActivityRecord(t: 2, lat: 30.2, lon: 120.8),
      ];
      final a = buildActivitySummary(_base(), rs);
      expect(a.lat, closeTo(30.1234567, 1e-9));
      expect(a.lon, closeTo(120.7654321, 1e-9));
    });

    test('移动时间不进汇总（桌面端只用会话值）', () {
      // 这条测试记录一个**刻意的行为**：即便 records 显示在移动，
      // buildActivitySummary 也不会自算 moving_s 填入。
      // `movingTime()` 仅在别处（如需展示"自算移动时间"）单独调用。
      final rs = [
        const ActivityRecord(t: 0, speedMs: 0.0),
        const ActivityRecord(t: 5, speedMs: 3.0),
        const ActivityRecord(t: 10, speedMs: 5.0),
        const ActivityRecord(t: 15, speedMs: 0.3),
        const ActivityRecord(t: 20, speedMs: 4.0),
      ];
      // 自算函数本身是对的（金标准 11.0）
      expect(movingTime(rs), 11.0);
      // 但 summary 不使用它
      final a = buildActivitySummary(_base(), rs);
      expect(a.movingS, isNull);
    });

    test('均值字段按 Python round() 取整（银行家舍入）', () {
      // 心率 100 与 101 → 均值 100.5
      // Python round(100.5) == 100（偶数），Dart 原生 100.5.round() == 101
      final rs = [
        const ActivityRecord(t: 0, hr: 100),
        const ActivityRecord(t: 1, hr: 101),
      ];
      final a = buildActivitySummary(_base(), rs);
      expect(a.avgHr, 100.0); // 必须是 100，不是 101
    });

    test('踏频均值同样走银行家舍入', () {
      final rs = [
        const ActivityRecord(t: 0, cad: 80),
        const ActivityRecord(t: 1, cad: 81),
      ];
      final a = buildActivitySummary(_base(), rs);
      expect(a.avgCad, 80.0);
    });

    test('已有汇总值不被覆盖（base 优先）', () {
      final base = const Activity(
        fileHash: 'x',
        startTime: '2026-09-20 08:00:00',
        startTs: 1758326400,
        month: '2026-09',
        totalDistanceM: 999.0,
        avgHr: 150.0,
      );
      final rs = [
        const ActivityRecord(t: 0, distM: 0, hr: 100),
        const ActivityRecord(t: 1, distM: 10, hr: 110),
      ];
      final a = buildActivitySummary(base, rs);
      expect(a.totalDistanceM, 999.0);
      expect(a.avgHr, 150.0);
    });
  });

  group('subSportToCn', () {
    test('已知映射', () {
      expect(subSportToCn('road'), '公路骑行');
      expect(subSportToCn('mountain'), '山地骑行');
      expect(subSportToCn('commuting'), '通勤');
      expect(subSportToCn('e_bike'), '电助力');
    });

    test('大小写不敏感', () {
      expect(subSportToCn('ROAD'), '公路骑行');
    });

    test('未知值原样返回', () {
      expect(subSportToCn('something_new'), 'something_new');
    });

    test('空值返回空串', () {
      expect(subSportToCn(null), '');
      expect(subSportToCn(''), '');
    });
  });
}
