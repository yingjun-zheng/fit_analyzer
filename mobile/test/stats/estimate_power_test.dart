/// 估算功率单测。
///
/// ⚠️ 期望值全部来自 fit_analyzer 桌面端 `core/analysis.py::estimate_power` 的实际输出。
library;

import 'package:flutter_test/flutter_test.dart';

import 'package:fit_analyzer_mobile/core/models/activity_record.dart';
import 'package:fit_analyzer_mobile/core/stats/estimate_power.dart';

ActivityRecord rec({
  required double t,
  double? distM,
  double? speedMs,
  double? hr,
  double? cad,
  double? altM,
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
      power: power,
      powerEstimated: powerEstimated,
    );

void main() {
  group('估算功率 estimatePower（物理模型）', () {
    test('平路匀速 —— 期望值来自桌面端（101 W）', () {
      // 桌面端实测：10 条记录，speed=7 m/s，alt 恒 100，dist 每点 +7
      //           → power = 101（恒定）
      final recs = [
        for (var i = 0; i < 10; i++)
          rec(t: i.toDouble(), distM: i * 7.0, speedMs: 7.0, altM: 100.0, hr: 140, cad: 85),
      ];
      final out = estimatePower(recs);
      expect(out.length, 10);
      for (final r in out) {
        expect(r.power, 101.0);
        expect(r.powerEstimated, isTrue);
      }
    });

    test('★ 已有功率时不估算（保持原值且不加标记）', () {
      // 桌面端实测：有 power 的记录原样返回，power_estimated 不存在
      final recs = [
        rec(t: 0, distM: 0, speedMs: 7.0, altM: 100.0, power: 200),
      ];
      final out = estimatePower(recs);
      expect(out[0].power, 200.0);
      expect(out[0].powerEstimated, isFalse);
    });

    test('爬坡场景 —— 期望值来自桌面端（266/293/320/348 W）', () {
      // 桌面端实测：grade ≈ 5%（每点 alt +0.35，dist +7）
      //           → t=5:266, t=6:293, t=7:320, t=8:348
      final recs = [
        for (var i = 0; i < 10; i++)
          rec(
            t: i.toDouble(),
            distM: i * 7.0,
            speedMs: 7.0,
            altM: 100.0 + i * 0.35,
            hr: 150,
            cad: 80,
          ),
      ];
      final out = estimatePower(recs);
      expect(out[5].power, 266.0);
      expect(out[6].power, 293.0);
      expect(out[7].power, 320.0);
      expect(out[8].power, 348.0);
    });

    test('估算结果全部标记 powerEstimated=true', () {
      final recs = [
        for (var i = 0; i < 20; i++)
          rec(t: i.toDouble(), distM: i * 5.0, speedMs: 5.0, altM: 50.0),
      ];
      final out = estimatePower(recs);
      expect(out.every((r) => r.powerEstimated), isTrue);
      expect(out.every((r) => r.power != null), isTrue);
    });

    test('功率不为负（下坡/减速时 clamp 到 0）', () {
      // 急速下坡：alt 快速下降
      final recs = [
        for (var i = 0; i < 20; i++)
          rec(t: i.toDouble(), distM: i * 15.0, speedMs: 15.0, altM: 200.0 - i * 2.0),
      ];
      final out = estimatePower(recs);
      expect(out.every((r) => (r.power ?? 0) >= 0), isTrue);
    });

    test('配置参数影响结果（体重越大功率越高）', () {
      final recs = [
        for (var i = 0; i < 20; i++)
          rec(t: i.toDouble(), distM: i * 7.0, speedMs: 7.0, altM: 100.0),
      ];
      final light = estimatePower(recs, config: const PowerEstimateConfig(riderWeightKg: 60));
      final heavy = estimatePower(recs, config: const PowerEstimateConfig(riderWeightKg: 90));
      expect(heavy[10].power! > light[10].power!, isTrue);
    });

    test('空输入返回空', () {
      expect(estimatePower(<ActivityRecord>[]).length, 0);
    });

    test('保留原始字段（不丢失 hr/cad 等）', () {
      final recs = [
        for (var i = 0; i < 10; i++)
          rec(t: i.toDouble(), distM: i * 7.0, speedMs: 7.0, altM: 100.0, hr: 142, cad: 88),
      ];
      final out = estimatePower(recs);
      expect(out[3].hr, 142.0);
      expect(out[3].cad, 88.0);
      expect(out[3].altM, 100.0);
    });
  });
}
