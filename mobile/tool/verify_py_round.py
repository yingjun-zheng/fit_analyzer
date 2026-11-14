"""验证 py_round.dart 的算法：与 Python 内置 round() 逐值比对。

这个脚本把 Dart 实现（BigInt 精确舍入）等价地翻译成 Python，
然后用大量随机 + 边界值验证是否与 round() 完全一致。
若一致，则 Dart 版本可信。
"""
import struct
import random
import math


def round_to_decimal_int(v: float, digits: int) -> int:
    """把 v 的精确值舍入到 digits 位小数，返回以 10^-digits 为单位的整数。"""
    if v == 0:
        return 0
    negative = v < 0
    a = abs(v)

    # 拆 IEEE 754
    raw = struct.pack('>d', a)
    hi, lo = struct.unpack('>II', raw)
    exp_bits = (hi >> 20) & 0x7FF
    mant_hi = hi & 0xFFFFF
    mantissa = (mant_hi << 32) | lo

    if exp_bits == 0:
        significand = mantissa
        bin_exp = -1074
    else:
        significand = mantissa | (1 << 52)
        bin_exp = exp_bits - 1075

    if digits >= 0:
        # v × 10^d = sig × 2^binExp × 2^d × 5^d = sig × 5^d × 2^(binExp + d)
        numerator = significand * (5 ** digits)
        e2 = bin_exp + digits
    else:
        numerator = significand
        e2 = bin_exp

    # 精确舍入 numerator × 2^e2
    if e2 >= 0:
        rounded = numerator << e2
    else:
        shift = -e2
        quotient = numerator >> shift
        remainder = numerator - (quotient << shift)
        if remainder == 0:
            rounded = quotient
        else:
            twice = remainder << 1
            half = 1 << shift
            if twice > half:
                rounded = quotient + 1
            elif twice < half:
                rounded = quotient
            else:
                rounded = quotient if quotient % 2 == 0 else quotient + 1

    return -rounded if negative else rounded


def py_round_mine(v: float, digits=None) -> float:
    """模拟 Dart 的 pyRound / pyRoundTo。"""
    if math.isnan(v) or math.isinf(v):
        return v
    d = 0 if digits is None else digits
    if d <= 0:
        # pyRound：只对精确值做整数 half-to-even
        r = round_to_decimal_int(v, 0)
        return r  # int 语义
    scaled = round_to_decimal_int(v, d)
    return float(f'{scaled}e{-d}')


def main():
    random.seed(42)

    cases = []
    # 手工边界
    manual = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, -0.5, -1.5, -2.5, -3.5,
              1.25, 1.35, 2.45, 1.005, 1.015, 0.05, 0.15,
              100.25, 100.35, 5.1235, 30.12345675,
              140.5, 0.0, 7.0, -3.0, 1e-7, 1.5e21, 0.1, 0.2, 0.3]
    for x in manual:
        for n in [None, 0, 1, 2, 3, 7]:
            cases.append((x, n))

    # 随机
    for _ in range(20000):
        x = random.uniform(-1000, 1000)
        n = random.choice([None, 0, 1, 2, 3, 4, 7])
        cases.append((x, n))
    # 随机 .5 家族
    for _ in range(20000):
        x = random.randint(-100000, 100000) / (10 ** random.randint(1, 3))
        n = random.choice([None, 0, 1, 2])
        cases.append((x, n))

    fails = 0
    for x, n in cases:
        try:
            expected = round(x) if n is None else round(x, n)
        except (OverflowError, ValueError):
            continue
        got = py_round_mine(x, n)
        if isinstance(expected, float) or isinstance(got, float):
            ok = (got == expected) or (math.isnan(got) and math.isnan(expected))
        else:
            ok = got == expected
        if not ok:
            fails += 1
            if fails <= 20:
                print(f'  MISMATCH x={x!r} n={n}: python={expected!r} mine={got!r}')
    print(f'\n共 {len(cases)} 例，失败 {fails} 例')
    print('算法与 Python round() ' + ('完全一致 ✔' if fails == 0 else '存在差异 ✘'))


if __name__ == '__main__':
    main()
