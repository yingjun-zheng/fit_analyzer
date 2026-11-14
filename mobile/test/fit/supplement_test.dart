// FIT 补充读取器测试
//
// 用**构造的** FIT 字节流验证 `readFitSupplement` 的解析逻辑
// （字段号、纪元换算、时区偏移、developer 字段步长、压缩时间戳）。
//
// 真实文件的端到端比对见 README「落地清单」——
// 那些文件不在仓库里，用 `mobile/tool/verify_fit_supplement.py` 离线校验。

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:fit_analyzer_mobile/core/fit/fit_enums.dart';
import 'package:fit_analyzer_mobile/core/fit/fit_supplement.dart';

/// 构造一个最小 FIT 文件：header + 若干记录。
class _FitBuilder {
  final _body = BytesBuilder();

  /// 写 definition message。
  ///
  /// [fields] 形如 `[(fieldNum, size, baseType), ...]`；
  /// [devFields] 形如 `[(fieldNum, size, devIndex), ...]`。
  void definition({
    required int localId,
    required int globalId,
    required List<(int, int, int)> fields,
    List<(int, int, int)> devFields = const [],
    bool littleEndian = true,
  }) {
    final hasDev = devFields.isNotEmpty;
    _body.addByte(0x40 | (hasDev ? 0x20 : 0x00) | (localId & 0x0F));
    _body.addByte(0); // reserved
    _body.addByte(littleEndian ? 0 : 1);
    // globalId uint16
    _body.addByte(globalId & 0xFF);
    _body.addByte((globalId >> 8) & 0xFF);
    _body.addByte(fields.length);
    for (final (num, size, btype) in fields) {
      _body.addByte(num);
      _body.addByte(size);
      _body.addByte(btype);
    }
    if (hasDev) {
      _body.addByte(devFields.length);
      for (final (num, size, devIdx) in devFields) {
        _body.addByte(num);
        _body.addByte(size);
        _body.addByte(devIdx);
      }
    }
  }

  /// 写 data message。[values] 按 definition 的字段顺序给出原始 uint32。
  void data({
    required int localId,
    required List<int> values,
    bool compressed = false,
  }) {
    if (compressed) {
      // 压缩时间戳帧：header bit7=1，localType 在 bit5-6
      _body.addByte(0x80 | ((localId & 0x03) << 5));
    } else {
      _body.addByte(localId & 0x0F);
    }
    for (final v in values) {
      _body.addByte(v & 0xFF);
      _body.addByte((v >> 8) & 0xFF);
      _body.addByte((v >> 16) & 0xFF);
      _body.addByte((v >> 24) & 0xFF);
    }
  }

  /// 写 developer 字段的占位数据（与 definition 的 devFields size 总和一致）。
  void devData(int bytes) {
    for (var i = 0; i < bytes; i++) {
      _body.addByte(0);
    }
  }

  void rawBytes(List<int> b) => _body.add(b);

  Uint8List build() {
    final bodyBytes = _body.toBytes();
    final header = BytesBuilder();
    header.addByte(14); // header_size
    header.addByte(0x10); // protocol
    header.addByte(0x00); // profile lo
    header.addByte(0x00); // profile hi
    final n = bodyBytes.length;
    header.addByte(n & 0xFF);
    header.addByte((n >> 8) & 0xFF);
    header.addByte((n >> 16) & 0xFF);
    header.addByte((n >> 24) & 0xFF);
    header.add([0x2E, 0x46, 0x49, 0x54]); // ".FIT"
    header.addByte(0);
    header.addByte(0);
    final out = BytesBuilder();
    out.add(header.toBytes());
    out.add(bodyBytes);
    return out.toBytes();
  }
}

/// FIT 时间戳（秒，相对 FIT 纪元）→ Unix 秒
int _fitSecs(int unixSecs) => unixSecs - kFitEpochUnixSeconds;

void main() {
  group('readFitSupplement', () {
    test('抽出 session.start_time 与 activity 的 local/timestamp', () {
      // 取一个可读的时间：2026-07-05 08:33:49 UTC
      const sessionStart = 1783211629;
      const actTs = 1783211629 + 10; // 结束时刻
      const offset = 28800; // 东八区
      const localTs = actTs + offset;

      final b = _FitBuilder();
      // session (global 18)：字段 2 = start_time
      b.definition(localId: 0, globalId: 18, fields: [(253, 4, 0x86), (2, 4, 0x86)]);
      b.data(localId: 0, values: [_fitSecs(actTs), _fitSecs(sessionStart)]);
      // activity (global 34)：字段 253 = timestamp, 5 = local_timestamp
      b.definition(localId: 1, globalId: 34, fields: [(253, 4, 0x86), (5, 4, 0x86)]);
      b.data(localId: 1, values: [_fitSecs(actTs), _fitSecs(localTs)]);

      final s = readFitSupplement(b.build());

      expect(s.sessionStartTime, isNotNull);
      expect(
        s.sessionStartTime!.millisecondsSinceEpoch ~/ 1000,
        sessionStart,
        reason: 'session.start_time 应精确还原',
      );
      expect(s.utcOffsetSeconds, offset, reason: '东八区偏移应为 +28800');
    });

    test('缺 local_timestamp 时偏移为 0', () {
      final b = _FitBuilder();
      b.definition(localId: 0, globalId: 34, fields: [(253, 4, 0x86)]);
      b.data(localId: 0, values: [_fitSecs(1783211629)]);

      final s = readFitSupplement(b.build());
      expect(s.activityTimestamp, isNotNull);
      expect(s.localTimestamp, isNull);
      expect(s.utcOffsetSeconds, 0);
    });

    test('偏移超过 ±14h 时不采信（与桌面端一致）', () {
      const actTs = 1783211629;
      final b = _FitBuilder();
      b.definition(localId: 0, globalId: 34, fields: [(253, 4, 0x86), (5, 4, 0x86)]);
      // 造一个 20 小时的差
      b.data(localId: 0, values: [_fitSecs(actTs), _fitSecs(actTs + 20 * 3600)]);

      final s = readFitSupplement(b.build());
      expect(s.utcOffsetSeconds, 0, reason: '超 14h 视为异常，退化为 0');
    });

    test('★ developer 字段步长为 3 字节，不会导致流失步', () {
      const sessionStart = 1783211629;
      final b = _FitBuilder();
      // 先来一条带 developer 字段的定义（模拟 lap），流必须能正确跳过
      b.definition(
        localId: 0,
        globalId: 19, // lap
        fields: [(253, 4, 0x86), (2, 4, 0x86)],
        devFields: [(0, 4, 0), (1, 2, 0), (2, 1, 0)], // 共 7 字节
      );
      b.data(localId: 0, values: [0, 0]);
      b.devData(7);
      // 再来 session，若上一步失步这里就读不到
      b.definition(localId: 1, globalId: 18, fields: [(2, 4, 0x86)]);
      b.data(localId: 1, values: [_fitSecs(sessionStart)]);

      final s = readFitSupplement(b.build());
      expect(
        s.sessionStartTime!.millisecondsSinceEpoch ~/ 1000,
        sessionStart,
        reason: 'developer 字段步长错误会导致后续消息全部读不到',
      );
    });

    test('非 FIT 字节流安全返回空值，不抛异常', () {
      final junk = Uint8List.fromList(List.generate(100, (i) => i & 0xFF));
      final s = readFitSupplement(junk);
      expect(s.localTimestamp, isNull);
      expect(s.activityTimestamp, isNull);
      expect(s.sessionStartTime, isNull);
      expect(s.utcOffsetSeconds, 0);
    });

    test('空字节流安全返回', () {
      final s = readFitSupplement(Uint8List(0));
      expect(s.utcOffsetSeconds, 0);
    });
  });

  group('fit_enums（与桌面端 fitparse 对齐）', () {
    test('sub_sport 数值 → 名称', () {
      expect(fitSubSportName(7), 'road');
      expect(fitSubSportName(8), 'mountain');
      expect(fitSubSportName(46), 'gravel_cycling');
      expect(fitSubSportName(48), 'commuting');
      expect(fitSubSportName(0), 'generic');
    });

    test('3 = trail / 4 = track（曾写反，勿回退）', () {
      expect(fitSubSportName(3), 'trail');
      expect(fitSubSportName(4), 'track');
    });

    test('厂商私有值返回 null（Magene 实测 252）', () {
      expect(fitSubSportName(252), isNull);
      expect(fitSubSportName(null), isNull);
    });

    test('sport 数值 → 名称', () {
      expect(fitSportName(2), 'cycling');
      expect(fitSportName(1), 'running');
      expect(fitSportName(0), 'generic');
      expect(fitSportName(999), isNull);
    });
  });
}
