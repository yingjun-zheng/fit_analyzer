/// FIT 解析适配层测试。
///
/// ⚠️ 本测试用**合成数据**验证适配层逻辑（平铺语义、距离补全、Python 舍入），
/// 不覆盖真实 FIT 二进制解析（那是 activity_files 的职责）。
///
/// **真实文件的端到端校验**见 `lib/core/fit/README.md` 的落地清单：
/// 需拿真实 iGPSPORT FIT 跑桌面端与移动端，逐字段比对。
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:fit_analyzer_mobile/core/models/activity.dart';
import 'package:fit_analyzer_mobile/core/models/activity_record.dart';
import 'package:fit_analyzer_mobile/core/stats/summarize.dart';

void main() {
  group('ActivityRecord', () {
    test('toMap / fromMap 往返', () {
      const r = ActivityRecord(
        t: 1.5,
        lat: 30.1234567,
        lon: 120.7654321,
        distM: 100.5,
        speedMs: 5.123,
        hr: 145,
        cad: 88,
        altM: 12.3,
        temp: 25.5,
        power: 210,
      );
      final back = ActivityRecord.fromMap(r.toMap());
      expect(back.t, 1.5);
      expect(back.lat, closeTo(30.1234567, 1e-9));
      expect(back.lon, closeTo(120.7654321, 1e-9));
      expect(back.distM, 100.5);
      expect(back.speedMs, 5.123);
      expect(back.hr, 145);
      expect(back.cad, 88);
      expect(back.altM, 12.3);
      expect(back.temp, 25.5);
      expect(back.power, 210);
      expect(back.powerEstimated, isFalse);
    });

    test('null 字段往返不丢失', () {
      const r = ActivityRecord(t: 0, distM: 10, speedMs: 1);
      final back = ActivityRecord.fromMap(r.toMap());
      expect(back.lat, isNull);
      expect(back.hr, isNull);
      expect(back.power, isNull);
      expect(back.distM, 10);
    });

    test('copyWith 只改指定字段', () {
      const r = ActivityRecord(t: 0, distM: 10, hr: 100);
      final b = r.copyWith(distM: 99);
      expect(b.distM, 99);
      expect(b.hr, 100);
      expect(b.t, 0);
    });

    test('powerEstimated 序列化', () {
      const r = ActivityRecord(t: 0, power: 200, powerEstimated: true);
      expect(r.toMap()['power_estimated'], 1);
      expect(ActivityRecord.fromMap(r.toMap()).powerEstimated, isTrue);
    });
  });

  group('Activity', () {
    Activity make({double? dist, double? timer, double? avgSpeed}) => Activity(
          fileHash: 'abc',
          fileName: 'ride.fit',
          startTime: '2026-09-20 08:00:00',
          startTs: 1758326400,
          month: '2026-09',
          totalDistanceM: dist,
          timerS: timer,
          avgSpeedMs: avgSpeed,
        );

    test('distanceKm / avgSpeedKmh / hours 派生属性', () {
      final a = make(dist: 42500, timer: 5400, avgSpeed: 7.0);
      expect(a.distanceKm, closeTo(42.5, 1e-9));
      expect(a.avgSpeedKmh, closeTo(25.2, 1e-9));
      expect(a.hours, closeTo(1.5, 1e-9));
    });

    test('缺字段时派生属性有安全默认', () {
      final a = make();
      expect(a.distanceKm, 0.0);
      expect(a.avgSpeedKmh, isNull);
      expect(a.hours, 0.0);
    });

    test('copyWith 可覆盖汇总字段', () {
      final a = make(dist: 1000);
      final b = a.copyWith(
        totalDistanceM: 2000,
        avgHr: 150,
        ascentM: 300.5,
        commute: true,
      );
      expect(b.totalDistanceM, 2000);
      expect(b.avgHr, 150);
      expect(b.ascentM, 300.5);
      expect(b.commute, isTrue);
      // 未指定字段保持
      expect(b.fileHash, 'abc');
      expect(b.month, '2026-09');
    });
  });

  group('ActivitySource', () {
    test('displayName 覆盖主要平台', () {
      expect(ActivitySource.localFile.displayName, isNotEmpty);
      expect(ActivitySource.garminCn.displayName, isNotEmpty);
      expect(ActivitySource.igpsport.displayName, isNotEmpty);
      expect(ActivitySource.xingzhe.displayName, isNotEmpty);
    });

    test('fromName 往返', () {
      for (final s in ActivitySource.values) {
        expect(ActivitySource.fromName(s.name), s);
      }
    });
  });

  group('汇总与解析联动（合成数据）', () {
    test('从 records 生成完整 Activity', () {
      final records = [
        for (var i = 0; i < 60; i++)
          ActivityRecord(
            t: i.toDouble(),
            lat: 30.0 + i * 1e-4,
            lon: 120.0 + i * 1e-4,
            distM: i * 7.0,
            speedMs: 7.0,
            hr: 140,
            cad: 85,
            altM: 100.0 + i * 0.5,
            temp: 25.0,
            power: 200,
          ),
      ];
      final base = Activity(
        fileHash: 'h',
        startTime: '2026-09-20 08:00:00',
        startTs: 1758326400,
        month: '2026-09',
      );
      final a = buildActivitySummary(base, records);

      expect(a.recordCount, 60);
      expect(a.totalDistanceM, closeTo(413.0, 1e-9)); // 59 * 7
      expect(a.timerS, closeTo(59.0, 1e-9));
      expect(a.avgHr, 140);
      expect(a.maxHr, 140);
      expect(a.avgCad, 85);
      expect(a.avgTemp, 25.0);
      expect(a.lat, closeTo(30.0, 1e-9));
      expect(a.lon, closeTo(120.0, 1e-9));
      // 持续爬升 0.5m/点，滞回阈值 1.0m。
      // 期望值 29.0 来自桌面端 accumulate_ascent_descent 实跑。
      expect(a.ascentM, closeTo(29.0, 1e-9));
      // 无会话 total_moving_time → moving_s 保持 null（桌面端口径）
      expect(a.movingS, isNull);
      expect(a.recordCount, 60);
    });
  });
}
