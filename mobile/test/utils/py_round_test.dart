/// Python 舍入语义复刻测试。
///
/// ⚠️ 期望值全部由 Python 解释器实跑 `round()` 得到。
/// 算法本身另有 40180 例穷举验证脚本：`tool/verify_py_round.py`。
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:fit_analyzer_mobile/core/utils/py_round.dart';

void main() {
  group('pyRound —— 复刻 Python round(x)', () {
    test('★ .5 处取偶（与 Dart 原生 round 的关键差异）', () {
      // Python: [round(x) for x in [0.5,1.5,2.5,3.5,4.5,5.5]]
      //         → [0, 2, 2, 4, 4, 6]
      expect(pyRound(0.5), 0);
      expect(pyRound(1.5), 2);
      expect(pyRound(2.5), 2);
      expect(pyRound(3.5), 4);
      expect(pyRound(4.5), 4);
      expect(pyRound(5.5), 6);
      // 对照：Dart 原生行为不同
      expect(0.5.round(), 1);
      expect(2.5.round(), 3);
    });

    test('负数的 half-to-even（Python: round(-0.5)=0, round(-1.5)=-2）', () {
      expect(pyRound(-0.5), 0);
      expect(pyRound(-1.5), -2);
      expect(pyRound(-2.5), -2);
      expect(pyRound(-3.5), -4);
    });

    test('非 .5 的常规舍入', () {
      expect(pyRound(0.4), 0);
      expect(pyRound(0.6), 1);
      expect(pyRound(1.4), 1);
      expect(pyRound(1.6), 2);
      expect(pyRound(2.49), 2);
      expect(pyRound(2.51), 3);
      expect(pyRound(-2.6), -3);
      expect(pyRound(-2.4), -2);
    });

    test('整数原样返回', () {
      expect(pyRound(0.0), 0);
      expect(pyRound(7.0), 7);
      expect(pyRound(-3.0), -3);
      expect(pyRound(140.0), 140);
    });

    test('特殊值不崩溃', () {
      expect(pyRound(double.nan), 0);
      expect(pyRound(double.infinity), 0);
      expect(pyRound(double.negativeInfinity), 0);
    });
  });

  group('pyRoundTo —— 复刻 Python round(x, digits)', () {
    test('★ 对精确二进制值舍入（不是乘 10^n 再舍）', () {
      // Python 实测（关键边界，朴素实现会错）：
      //   round(0.05, 1) == 0.1   朴素法 pyRound(0.05*10)/10 = 0.0
      //   round(2.45, 1) == 2.5   朴素法 pyRound(2.45*10)/10 = 2.4
      expect(pyRoundTo(0.05, 1), 0.1);
      expect(pyRoundTo(2.45, 1), 2.5);
    });

    test('一位小数', () {
      // Python: round(1.25,1)=1.2, round(1.35,1)=1.4, round(0.15,1)=0.1,
      //         round(100.25,1)=100.2, round(100.35,1)=100.3
      expect(pyRoundTo(1.25, 1), 1.2);
      expect(pyRoundTo(1.35, 1), 1.4);
      expect(pyRoundTo(0.15, 1), 0.1);
      expect(pyRoundTo(100.25, 1), 100.2);
      expect(pyRoundTo(100.35, 1), 100.3);
    });

    test('两位小数', () {
      // Python: round(1.005,2)=1.0, round(1.015,2)=1.01
      expect(pyRoundTo(1.005, 2), 1.0);
      expect(pyRoundTo(1.015, 2), 1.01);
    });

    test('三位小数（fit_parser 的 round(speed,3)）', () {
      // Python: round(5.1235,3)=5.123
      expect(pyRoundTo(5.1235, 3), 5.123);
      expect(pyRoundTo(5.1234, 3), closeTo(5.123, 1e-12));
    });

    test('七位小数（fit_parser 的 round(lat,7)）', () {
      // Python: round(30.12345675,7)=30.1234567
      expect(pyRoundTo(30.12345675, 7), 30.1234567);
    });

    test('digits<=0 退化为整数舍入', () {
      expect(pyRoundTo(1.5, 0), 2.0);
      expect(pyRoundTo(2.5, 0), 2.0);
      expect(pyRoundTo(0.5, 0), 0.0);
    });

    test('常规值不引入误差', () {
      expect(pyRoundTo(1.23456, 2), 1.23);
      expect(pyRoundTo(-1.23456, 2), -1.23);
      expect(pyRoundTo(100.0, 1), 100.0);
    });

    test('特殊值不崩溃', () {
      expect(pyRoundTo(double.nan, 1).isNaN, isTrue);
      expect(pyRoundTo(double.infinity, 1), double.infinity);
    });

    test('★ 与朴素实现的差异（说明为何必须复刻）', () {
      // 朴素法（乘 10^n → Dart round → 除回去）在边界上偏离 Python：
      //   (0.05 * 10) == 0.5 → Dart round = 1 → 0.1 ... 但这是巧合
      //   真正的差异在 2.45：Python round(2.45,1) == 2.5，
      //   而 pyRound(2.45*10)/10 会看 24.5 的精确值决定，结果不同。
      // 这里只断言 Python 口径，并对常用值确认无偏差。
      expect(pyRoundTo(0.05, 1), 0.1);
      expect(pyRoundTo(2.45, 1), 2.5);
      expect(pyRoundTo(1.25, 1), 1.2);

      // 对"正常"数值（非 .5 边界），两种实现应当一致
      for (final v in [1.234, 5.678, 99.999, 0.1, 3.14159]) {
        expect(
          pyRoundTo(v, 2),
          closeTo(double.parse(v.toStringAsFixed(2)), 1e-12),
        );
      }
    });
  });
}
