/// 数值工具：复刻 Python 的舍入语义。
///
/// **为什么需要这个**：fit_analyzer 桌面端是 Python 实现，全程使用 Python 内置
/// `round()`。Dart 与 Python 有两处不一致：
///
/// 1. **`.5` 的处理方向**
///    Python: 银行家舍入（round-half-to-even）
///      round(0.5)==0, round(1.5)==2, round(2.5)==2, round(-0.5)==0
///    Dart `double.round()`: 四舍五入远离零
///      0.5.round()==1, 2.5.round()==3, (-0.5).round()==-1
///
/// 2. **`round(x, n)` 的基准**
///    Python 的 `round(x, n)` 是对 x 的**精确二进制值**做十进制 ROUND_HALF_EVEN，
///    不是"乘 10^n → 舍入 → 除回去"。已验证：
///      Python round(0.05, 1) == 0.1
///        （0.05 的 double 精确值 = 0.0500000000000000027755...，十进制第 2 位 >5 → 进）
///      而朴素法 pyRound(0.05 * 10) / 10 == pyRound(0.5) / 10 == 0.0  ← 错
///      Python round(2.45, 1) == 2.5
///        （2.45 精确值 = 2.45000000000000017763...，第 2 位 >5 → 进）
///      朴素法 pyRound(2.45 * 10) / 10 == pyRound(24.5) / 10 == 24 / 10 == 2.4  ← 错
///
/// 因桌面端几乎每个数值字段都要 round（心率/踏频/功率/秒数/米数），这类偏差
/// 会累积成可见的 1 单位差异，保真度检查必然失败。故必须精确复刻。
///
/// **实现方式**：从 IEEE 754 位模式还原 x 的精确有理数（mantissa × 2^exp），
/// 再用 BigInt 做十进制定点舍入。不依赖 double 运算，结果与 Python 逐位一致。
library;

import 'dart:typed_data';

/// 复刻 Python `round(x)` → int（对精确值做 half-to-even）。
int pyRound(double v) {
  if (v.isNaN || v.isInfinite) return 0;
  return _roundToDecimalInt(v, 0);
}

/// 复刻 Python `round(x, digits)` → double（对精确值做十进制 half-to-even）。
///
/// [digits] 为保留的小数位数。返回的 double 是"精确舍入后的十进制值"再转回
/// double；与 Python 的 `float(round(x, n))` 一致。
double pyRoundTo(double v, int digits) {
  if (v.isNaN || v.isInfinite) return v;
  if (digits <= 0) return pyRound(v).toDouble();

  // 把 x 舍入到 10^-digits 的整数倍，结果 = roundedInt × 10^-digits
  final scaled = _roundToDecimalInt(v, digits);
  return _bigIntTimesPow10(scaled, -digits);
}

/// 把 [v] 的**精确值**舍入到 [digits] 位小数，返回以 10^-digits 为单位的整数。
///
/// 即返回 round_half_even(v × 10^digits)。全程 BigInt 精确运算。
BigInt _roundToDecimalInt(double v, int digits) {
  if (v == 0) return BigInt.zero;

  final negative = v < 0;
  final abs = v.abs();

  // ---- 1. 拆解 IEEE 754 double ----
  final bits = ByteData(8)..setFloat64(0, abs, Endian.big);
  final hi = bits.getUint32(0, Endian.big);
  final lo = bits.getUint32(4, Endian.big);
  final expBits = (hi >> 20) & 0x7FF;
  final mantHi = hi & 0xFFFFF;
  final mantissa = (BigInt.from(mantHi) << 32) | BigInt.from(lo);

  // 精确值 = significand × 2^(-52) × 2^(expBits - 1023)
  //        = significand × 2^(expBits - 1075)     （normal）
  //        = mantissa    × 2^(-1074)              （subnormal, expBits == 0）
  final BigInt significand;
  final int binExp; // 值 = significand × 2^binExp
  if (expBits == 0) {
    significand = mantissa;
    binExp = -1074;
  } else {
    significand = mantissa | (BigInt.one << 52);
    binExp = expBits - 1075;
  }

  // ---- 2. 统一为「整数 × 2^e2」形式，再乘 10^digits ----
  // v × 10^digits = significand × 2^binExp × 10^digits
  //               = significand × 2^binExp × 2^digits × 5^digits
  //               = significand × 5^digits × 2^(binExp + digits)
  final BigInt numerator;
  final int e2;
  if (digits >= 0) {
    numerator = significand * BigInt.from(5).pow(digits);
    e2 = binExp + digits;
  } else {
    // digits < 0：除以 10^|digits|，不在此路径（上层已处理 digits<=0）
    numerator = significand;
    e2 = binExp;
  }

  // ---- 3. 精确舍入 numerator × 2^e2 → BigInt（half-to-even） ----
  final BigInt rounded;
  if (e2 >= 0) {
    rounded = numerator << e2;
  } else {
    final shift = -e2;
    final quotient = numerator >> shift;
    final remainder = numerator - (quotient << shift);
    if (remainder == BigInt.zero) {
      rounded = quotient;
    } else {
      final twiceRem = remainder << 1;
      final half = BigInt.one << shift; // 2^shift
      if (twiceRem > half) {
        rounded = quotient + BigInt.one;
      } else if (twiceRem < half) {
        rounded = quotient;
      } else {
        // 恰好 .5 → half-to-even
        rounded = quotient.isEven ? quotient : quotient + BigInt.one;
      }
    }
  }

  return negative ? -rounded : rounded;
}

/// BigInt × 10^exp → double。
///
/// 直接在十进制串上 `double.parse`，避免中间乘法引入误差。
double _bigIntTimesPow10(BigInt digits, int exp) {
  final s = digits.toString();
  if (exp == 0) return double.parse(s);

  final negative = s.startsWith('-');
  final body = negative ? s.substring(1) : s;

  final StringBuilder = StringBuffer();
  if (negative) StringBuilder.write('-');

  if (exp > 0) {
    StringBuilder.write(body);
    for (var i = 0; i < exp; i++) {
      StringBuilder.write('0');
    }
  } else {
    final pointAt = body.length + exp;
    if (pointAt > 0) {
      StringBuilder.write(body.substring(0, pointAt));
      StringBuilder.write('.');
      StringBuilder.write(body.substring(pointAt));
    } else {
      StringBuilder.write('0.');
      for (var i = 0; i < -pointAt; i++) {
        StringBuilder.write('0');
      }
      StringBuilder.write(body);
    }
  }

  final result = double.parse(StringBuilder.toString());
  return result;
}
