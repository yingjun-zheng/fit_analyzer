/// 统计算法单测。
///
/// ⚠️ **每个测试的期望值都来自 fit_analyzer 桌面端的实际输出**
/// （用 Python 跑 `core/analysis.py` / `core/training_load.py` 得到）。
/// 这是"继承正确性"的具体手段：如果这些测试通过，说明移动端算法与桌面端一致。
///
/// 修改算法时，必须先确认桌面端是否也改了；如果只改一端，测试会失败 —— 这是
/// 设计意图（防止口径漂移）。
///
/// 直接跑：`dart test test/stats/`
library;

import 'package:flutter_test/flutter_test.dart';

import 'package:fit_analyzer_mobile/core/models/activity_record.dart';
import 'package:fit_analyzer_mobile/core/stats/analysis.dart';
import 'package:fit_analyzer_mobile/core/stats/metrics.dart';
import 'package:fit_analyzer_mobile/core/stats/training_load.dart';

/// 构造测试用 record 的便捷方法。
ActivityRecord rec({
  required double t,
  double? distM,
  double? speedMs,
  double? hr,
  double? cad,
  double? altM,
  double? temp,
  double? power,
  bool powerEstimated = false,
}) =>
    ActivityRecord(
      t: t,
      distM: distM,
      speedMs: speedMs,
      hr: hr,
      cad: cad,
      altM: altM,
      temp: temp,
      power: power,
      powerEstimated: powerEstimated,
    );

void main() {
  group('爬升/下降 accumulateAscentDescent（滞回参考点法）', () {
    test('标准场景 —— 期望值来自桌面端 core/analysis.py', () {
      // 桌面端实测：eles=[100,100.5,101.8,101.2,102.5,103.0,102.0,104.5,99.0]
      //           → ascent=5.5, descent=6.5
      const eles = <double?>[
        100.0, 100.5, 101.8, 101.2, 102.5, 103.0, 102.0, 104.5, 99.0
      ];
      final r = accumulateAscentDescent(eles);
      expect(r.ascent, 5.5);
      expect(r.descent, 6.5);
    });

    test('null 值跳过（不影响累计）', () {
      const eles = <double?>[100.0, null, 102.0, null, 103.0];
      final r = accumulateAscentDescent(eles);
      // 与 [100,102,103] 结果一致
      final r2 = accumulateAscentDescent(const <double?>[100.0, 102.0, 103.0]);
      expect(r.ascent, r2.ascent);
      expect(r.descent, r2.descent);
    });

    test('阈值内抖动不灌水（关键：朴素算法会累成 1.2）', () {
      // ±0.5 抖动，每个差值 < 1.0 阈值 → 不应计入
      const eles = <double?>[100.0, 100.5, 100.0, 100.5, 100.0, 100.5];
      final r = accumulateAscentDescent(eles);
      expect(r.ascent, 0.0);
      expect(r.descent, 0.0);
    });

    test('空列表与单点返回 0', () {
      expect(accumulateAscentDescent(const <double?>[]).ascent, 0.0);
      expect(accumulateAscentDescent(const <double?>[100.0]).ascent, 0.0);
    });

    test('全 null 返回 0', () {
      final r = accumulateAscentDescent(const <double?>[null, null, null]);
      expect(r.ascent, 0.0);
      expect(r.descent, 0.0);
    });
  });

  group('移动时间 movingTime', () {
    test('标准场景 —— 期望值来自桌面端', () {
      // 桌面端实测：speed=[0.0,3.0,5.0,0.3,4.0], t=[0,5,10,15,20]
      //           → moving_time=11.0
      // 说明：speed>0.5 的索引为 1(3.0)、2(5.0)、4(4.0)
      //       索引1: dt = t[2]-t[1] = 5
      //       索引2: dt = t[3]-t[2] = 5
      //       索引4: 最后一条，dt = 1.0
      //       合计 = 11.0
      final recs = [
        rec(t: 0, speedMs: 0.0),
        rec(t: 5, speedMs: 3.0),
        rec(t: 10, speedMs: 5.0),
        rec(t: 15, speedMs: 0.3),
        rec(t: 20, speedMs: 4.0),
      ];
      expect(movingTime(recs), 11.0);
    });

    test('阈值边界：0.5 不算移动（严格大于）', () {
      final recs = [rec(t: 0, speedMs: 0.5), rec(t: 10, speedMs: 0.51)];
      // 索引1 满足 >0.5，且是最后一条 → dt=1.0
      expect(movingTime(recs), 1.0);
    });

    test('全静止返回 0', () {
      final recs = [rec(t: 0, speedMs: 0.0), rec(t: 10, speedMs: 0.0)];
      expect(movingTime(recs), 0.0);
    });

    test('null 速度视为 0', () {
      final recs = [rec(t: 0), rec(t: 10)];
      expect(movingTime(recs), 0.0);
    });
  });

  group('区间时间加权 weightedZoneTimes', () {
    test('心率 5 区 —— 期望值来自桌面端', () {
      // 桌面端实测：max_hr=180, hr=[100,115,130,145,165,175,120], t=0,4,8,12,16,20,24
      // 边界 [108, 126, 144, 162]
      //           → z1=4.0 z2=5.0 z3=4.0 z4=4.0 z5=8.0
      final hrs = [100.0, 115.0, 130.0, 145.0, 165.0, 175.0, 120.0];
      final recs = [
        for (var i = 0; i < hrs.length; i++) rec(t: i * 4.0, hr: hrs[i]),
      ];
      const mhr = 180.0;
      final bounds = [for (final p in hrZonePcts) mhr * p];
      final zones = weightedZoneTimes(recs, (r) => r.hr, bounds);

      expect(zones.length, 5);
      expect(zones[0].seconds, 4.0);
      expect(zones[1].seconds, 5.0);
      expect(zones[2].seconds, 4.0);
      expect(zones[3].seconds, 4.0);
      expect(zones[4].seconds, 8.0);

      // 百分比：total=25
      expect(zones[0].pct, 16.0);
      expect(zones[4].pct, 32.0);
    });

    test('dt 上限 30 秒（长间隔被截断）', () {
      // 两条记录间隔 100 秒 → dt 应为 30，不是 100
      final recs = [rec(t: 0, hr: 150), rec(t: 100, hr: 150)];
      const mhr = 200.0;
      final bounds = [for (final p in hrZonePcts) mhr * p];
      final zones = weightedZoneTimes(recs, (r) => r.hr, bounds);
      // 索引0: dt = min(100,30) = 30；索引1: 最后一条 dt=1.0 → total 31
      final total = zones.fold<double>(0, (a, z) => a + z.seconds);
      expect(total, 31.0);
    });

    test('dt=0 时取 1.0', () {
      // 两条记录同 t
      final recs = [rec(t: 5, hr: 150), rec(t: 5, hr: 150)];
      const mhr = 200.0;
      final bounds = [for (final p in hrZonePcts) mhr * p];
      final zones = weightedZoneTimes(recs, (r) => r.hr, bounds);
      final total = zones.fold<double>(0, (a, z) => a + z.seconds);
      // 索引0: dt=0 → 1.0；索引1: dt=1.0 → total 2.0
      expect(total, 2.0);
    });

    test('null 值不计入总时长', () {
      final recs = [rec(t: 0, hr: null), rec(t: 10, hr: 150), rec(t: 20, hr: null)];
      const mhr = 200.0;
      final bounds = [for (final p in hrZonePcts) mhr * p];
      final zones = weightedZoneTimes(recs, (r) => r.hr, bounds);
      final total = zones.fold<double>(0, (a, z) => a + z.seconds);
      // 仅索引1 计入（dt=10），索引0/2 的 hr 为 null 跳过
      // 索引1 有下一条(t=20) → dt = 20-10 = 10
      expect(total, 10.0);
    });

    test('空记录返回 5 个零区间', () {
      final zones = weightedZoneTimes(<ActivityRecord>[], (r) => r.hr,
          [100.0, 120.0, 140.0, 160.0]);
      expect(zones.length, 5);
      expect(zones.every((z) => z.seconds == 0.0), isTrue);
      expect(zones.every((z) => z.pct == 0.0), isTrue);
    });
  });

  group('抽稀 downsampleSeries', () {
    test('点数少于上限时原样返回', () {
      final recs = [for (var i = 0; i < 10; i++) rec(t: i.toDouble(), hr: 100 + i.toDouble())];
      final pts = downsampleSeries(recs, (r) => r.hr, maxPoints: 100);
      expect(pts.length, 10);
      expect(pts.first.t, 0.0);
      expect(pts.last.v, 109.0);
    });

    test('超限时按等间隔索引采样', () {
      final recs = [for (var i = 0; i < 1000; i++) rec(t: i.toDouble(), hr: 100.0)];
      final pts = downsampleSeries(recs, (r) => r.hr, maxPoints: 100);
      expect(pts.length, 100);
      // 第一个点是索引 0，t=0
      expect(pts.first.t, 0.0);
      // step = 1000/100 = 10 → 最后 idx = 99*10 = 990，min(999,990)=990
      expect(pts.last.t, 990.0);
    });

    test('null 值被过滤掉', () {
      final recs = [
        rec(t: 0, hr: 100),
        rec(t: 1, hr: null),
        rec(t: 2, hr: 120),
      ];
      final pts = downsampleSeries(recs, (r) => r.hr, maxPoints: 100);
      expect(pts.length, 2);
      expect(pts[0].v, 100.0);
      expect(pts[1].v, 120.0);
    });
  });

  group('按公里分桶 perKm', () {
    test('两公里分桶（期望结构来自桌面端）', () {
      // 构造：0~1000m 一点，1000~2000m 一点
      final recs = [
        rec(t: 0, distM: 0, speedMs: 5.0, hr: 120, cad: 80, altM: 100),
        rec(t: 100, distM: 500, speedMs: 5.0, hr: 130, cad: 82, altM: 110),
        rec(t: 200, distM: 1000, speedMs: 6.0, hr: 140, cad: 84, altM: 120),
        rec(t: 300, distM: 1500, speedMs: 6.0, hr: 150, cad: 86, altM: 130),
      ];
      final buckets = perKm(recs);
      expect(buckets.length, 2);

      // 第 0 桶：km=0，t0=0 t1=200（注意 dist=1000 属于 km=1 的桶）
      // 分类：distM 0→km0, 500→km0, 1000→km1, 1500→km1
      expect(buckets[0].km, 0);
      expect(buckets[1].km, 1);
      expect(buckets[0].avgHr, 125.0); // (120+130)/2
      expect(buckets[1].avgHr, 145.0); // (140+150)/2
    });

    test('空记录返回空列表', () {
      expect(perKm(<ActivityRecord>[]).length, 0);
    });
  });

  group('轨迹抽稀 trackPoints', () {
    test('少于上限时保留全部', () {
      final recs = [
        rec(t: 0, lat: 30.0, lon: 120.0, altM: 10),
        rec(t: 1, lat: 30.1, lon: 120.1, altM: 11),
      ];
      final pts = trackPoints(recs, maxPoints: 100);
      expect(pts.length, 2);
      expect(pts[0].lat, 30.0);
      expect(pts[1].lon, 120.1);
    });

    test('保证首尾点存在', () {
      final recs = [
        for (var i = 0; i < 1000; i++)
          rec(t: i.toDouble(), lat: 30.0 + i * 0.001, lon: 120.0, altM: 10),
      ];
      final pts = trackPoints(recs, maxPoints: 100);
      expect(pts.length, 100);
      expect(pts.first.lat, 30.0);
      expect(pts.last.lat, closeTo(30.999, 0.0001));
    });

    test('无经纬度的点被过滤', () {
      final recs = [
        rec(t: 0, lat: 30.0, lon: 120.0),
        rec(t: 1, altM: 10),
        rec(t: 2, lat: 30.1, lon: 120.1),
      ];
      final pts = trackPoints(recs, maxPoints: 100);
      expect(pts.length, 2);
    });

    test('全无坐标返回空', () {
      final recs = [rec(t: 0, hr: 100), rec(t: 1, hr: 110)];
      expect(trackPoints(recs).length, 0);
    });
  });

  group('温度统计 tempStats', () {
    test('正常统计', () {
      final recs = [rec(t: 0, temp: 20.0), rec(t: 1, temp: 25.0), rec(t: 2, temp: 15.0)];
      final s = tempStats(recs);
      expect(s.has, isTrue);
      expect(s.min, 15.0);
      expect(s.max, 25.0);
      expect(s.avg, 20.0);
    });

    test('无温度返回 has=false', () {
      final s = tempStats([rec(t: 0, hr: 100)]);
      expect(s.has, isFalse);
      expect(s.min, isNull);
    });
  });

  group('NP 归一化功率 normalizedPower', () {
    test('标准场景 —— 期望值来自桌面端', () {
      // 桌面端实测：power=[200,220,240,260,180,210,230,250,190,205]
      //           → NP=218.4, avg=218.5
      final recs = [
        rec(t: 0, power: 200),
        rec(t: 1, power: 220),
        rec(t: 2, power: 240),
        rec(t: 3, power: 260),
        rec(t: 4, power: 180),
        rec(t: 5, power: 210),
        rec(t: 6, power: 230),
        rec(t: 7, power: 250),
        rec(t: 8, power: 190),
        rec(t: 9, power: 205),
      ];
      final r = normalizedPower(recs);
      expect(r.np, 218.4);
      expect(r.avgPower, 218.5);
    });

    test('无功率返回 null', () {
      final r = normalizedPower([rec(t: 0, hr: 100)]);
      expect(r.np, isNull);
      expect(r.avgPower, isNull);
    });

    test('少于 30 点时窗口取实际长度', () {
      final recs = [rec(t: 0, power: 100), rec(t: 1, power: 200)];
      final r = normalizedPower(recs);
      expect(r.np, isNotNull);
      expect(r.np! > 100 && r.np! < 200, isTrue);
    });
  });

  group('TSS computeActivityTss', () {
    test('有功率+FTP 走功率路径 —— 期望值来自桌面端', () {
      // 桌面端实测：power=[200..205] (10 条), ftp=250
      //           → TSS=0.2, method=power, NP=218.4, intensity=0.87
      final recs = [
        rec(t: 0, power: 200),
        rec(t: 1, power: 220),
        rec(t: 2, power: 240),
        rec(t: 3, power: 260),
        rec(t: 4, power: 180),
        rec(t: 5, power: 210),
        rec(t: 6, power: 230),
        rec(t: 7, power: 250),
        rec(t: 8, power: 190),
        rec(t: 9, power: 205),
      ];
      final r = computeActivityTss(recs, ftp: 250);
      expect(r.method, 'power');
      expect(r.tss, 0.2);
      expect(r.npW, 218.4);
      expect(r.intensity, 0.87);
    });

    test('★ 估算功率不得用于 TSS（关键约束）', () {
      // 全部为估算功率 → 不应走功率路径
      final recs = [
        rec(t: 0, power: 200, powerEstimated: true),
        rec(t: 1, power: 220, powerEstimated: true),
      ];
      final r = computeActivityTss(recs, ftp: 250);
      expect(r.method, isNot('power'));
    });

    test('无功率有心率走 hrTSS', () {
      final recs = [
        for (var i = 0; i < 60; i++) rec(t: i.toDouble(), hr: 150.0),
      ];
      final r = computeActivityTss(recs, maxHr: 180);
      expect(r.method, 'hr');
      expect(r.tss, isNotNull);
      expect(r.tss! > 0, isTrue);
    });

    test('都无返回空结果', () {
      final recs = [rec(t: 0, speedMs: 5.0), rec(t: 1, speedMs: 6.0)];
      final r = computeActivityTss(recs);
      expect(r.tss, isNull);
      expect(r.method, isNull);
    });

    test('FTP=0 不走功率路径', () {
      final recs = [rec(t: 0, power: 200), rec(t: 1, power: 220)];
      final r = computeActivityTss(recs, ftp: 0);
      expect(r.method, isNot('power'));
    });
  });

  group('CTL/ATL/TSB 曲线', () {
    test('连续两天正常计算', () {
      final daily = [('2026-09-01', 100.0), ('2026-09-02', 50.0)];
      final c = buildPerformanceCurve(daily);
      expect(c.ctl.containsKey('2026-09-01'), isTrue);
      expect(c.atl.containsKey('2026-09-02'), isTrue);
      expect(c.latest, isNotNull);
      expect(c.latest!.date, '2026-09-02');
    });

    test('★ 空档天数参与衰减（关键：不能保持高位）', () {
      // 第 1 天 TSS=100，然后空档 60 天，第 62 天 TSS=0
      final daily = [('2026-01-01', 100.0), ('2026-03-04', 0.0)];
      final c = buildPerformanceCurve(daily);
      final ctlEnd = c.ctl['2026-03-04']!;
      // 经过 62 天衰减，CTL 应显著低于 100
      expect(ctlEnd < 30, isTrue);
    });

    test('TSB = CTL - ATL', () {
      final daily = [('2026-09-01', 100.0)];
      final c = buildPerformanceCurve(daily);
      final d = '2026-09-01';
      expect(c.tsb[d], closeTo(c.ctl[d]! - c.atl[d]!, 0.05));
    });

    test('空输入不崩溃', () {
      final c = buildPerformanceCurve([]);
      expect(c.latest, isNull);
    });
  });

  group('recentWeekTss 最近 N 天', () {
    test('窗口内求和', () {
      final daily = [
        ('2026-09-01', 10.0),
        ('2026-09-05', 20.0),
        ('2026-09-10', 30.0),
      ];
      // 锚点 09-10，向前 7 天 = 09-04 ~ 09-10 → 只含 09-05 和 09-10
      expect(recentWeekTss(daily, days: 7), 50.0);
    });

    test('空输入返回 0', () {
      expect(recentWeekTss([], days: 7), 0.0);
    });
  });

  group('恢复建议 recoveryAdvice', () {
    test('各档位文案', () {
      expect(recoveryAdvice(null), contains('无法评估'));
      expect(recoveryAdvice(-35), contains('深度疲劳'));
      expect(recoveryAdvice(-20), contains('疲劳累积'));
      expect(recoveryAdvice(0), contains('负荷适中'));
      expect(recoveryAdvice(20), contains('状态良好'));
      expect(recoveryAdvice(30), contains('过度恢复'));
    });
  });

  group('常量与桌面端一致（防口径漂移）', () {
    test('海拔噪声阈值 = 1.0', () {
      expect(altitudeNoiseThresholdM, 1.0);
    });

    test('移动速度阈值 = 0.5 m/s', () {
      expect(movingSpeedThresholdMs, 0.5);
    });

    test('区间 dt 上限 = 30 秒', () {
      expect(maxZoneDtSeconds, 30.0);
    });

    test('曲线抽稀点数 = 600 / 2000', () {
      expect(defaultSeriesMaxPoints, 600);
      expect(defaultTrackMaxPoints, 2000);
    });

    test('心率区边界与 IF 映射', () {
      expect(hrZonePcts, [0.6, 0.7, 0.8, 0.9]);
      expect(hrZoneIntensityFactors, [0.50, 0.65, 0.75, 0.85, 0.95]);
    });

    test('CTL/ATL 时间常数 = 42 / 7 天', () {
      expect(ctlTau, 42.0);
      expect(atlTau, 7.0);
    });
  });
}
