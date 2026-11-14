// FIT 补充读取器：补齐 `activity_files` 未暴露的两个关键标量。
//
// ⚠️ 为什么需要这个文件（这是与桌面端口径对齐的**硬需求**）：
//
//   1) `activity.local_timestamp`（FIT activity 消息，global 34，字段 5）
//      桌面端 core/fit_parser.py:160-170 用它推算本地时区偏移：
//          utc_offset_s = local_timestamp - timestamp   （|diff| ≤ 14h 才采信）
//      这个偏移决定了 `start_time` 显示值与 `month` 归属，**必须准确**。
//      实测 iGPSPORT 文件 local=12:53:25 / ts=04:53:25 → +28800s（东八区）。
//
//   2) `session.start_time`（FIT session 消息，global 18，字段 2）
//      桌面端 core/fit_parser.py:151 用 `session.start_time` 作为活动起点，
//      只在其缺失时才退化为首条 record 时间。实测二者常差 1-2 秒，
//      若直接用首条 record，会导致全部记录的 `t` 相对桌面端整体偏移。
//
//   `activity_files` 0.7.8 的 FIT 解析器**丢弃**了这两项：
//     - `case 34`（activity）只读字段 0（total_timer_time），字段 5 直接忽略；
//     - `case 18`（session）构建 ActivitySummary 时不含 start_time；
//     - 且 `RawActivity.metadata` 在 FIT 路径下始终为空 Map。
//   （取证位置：activity_files-0.7.8/lib/src/parse/fit_parser.dart:836、616-644）
//
// 本文件是一个**只读、最小化**的 FIT 扫描器：不做任何数值换算（scale/offset），
// 只按 baseType 原样取出 uint32 时间戳，然后换算成 UTC DateTime。
// FIT 时间戳纪元 = 1989-12-31T00:00:00Z（即 Unix 631065600）。

import 'dart:typed_data';

/// FIT 时间戳纪元（1989-12-31T00:00:00Z）对应的 Unix 秒。
const int kFitEpochUnixSeconds = 631065600;

/// FIT activity 消息的 global message number。
const int _msgActivity = 34;

/// FIT session 消息的 global message number。
const int _msgSession = 18;

/// 从 FIT 中补充出的两个值。
class FitSupplement {
  const FitSupplement({
    this.localTimestamp,
    this.activityTimestamp,
    this.sessionStartTime,
  });

  /// activity.local_timestamp（本地墙上时间，无时区含义）。
  final DateTime? localTimestamp;

  /// activity.timestamp（UTC）。
  final DateTime? activityTimestamp;

  /// session.start_time（UTC）。
  final DateTime? sessionStartTime;

  /// 本地时区偏移（秒）。取不到或超出 ±14h 时返回 0，与桌面端一致。
  int get utcOffsetSeconds {
    final lt = localTimestamp;
    final ts = activityTimestamp;
    if (lt == null || ts == null) return 0;
    // 二者都是「同一瞬间」的两种表达，差值即偏移。
    // 注意：localTimestamp 是按 UTC 直接解读的墙上时间，不能再叠加本机时区。
    final diff = lt.difference(ts).inSeconds;
    if (diff.abs() <= 14 * 3600) return diff;
    return 0;
  }
}

/// 扫描 FIT 字节流，抽出 local_timestamp / activity.timestamp / session.start_time。
///
/// 只解析 definition(0x40) 与 data(0x00 / 0x80) 两类记录，
/// 遇到任何结构异常立即返回已得结果（绝不抛异常），保证不会影响主解析路径。
FitSupplement readFitSupplement(Uint8List bytes) {
  DateTime? localTs;
  DateTime? actTs;
  DateTime? sessionStart;

  try {
    if (bytes.length < 14) return const FitSupplement();

    // ---- FIT 文件头 ----
    // 0: header_size (通常 14，可为 12)
    // 1: protocol_version, 2-3: profile_version
    // 4-7: data_size (uint32 LE)
    // 8-11: ".FIT"
    final headerSize = bytes[0];
    if (headerSize < 12 || headerSize > bytes.length) {
      return const FitSupplement();
    }

    var pos = headerSize;
    final dataSize =
        bytes[4] | (bytes[5] << 8) | (bytes[6] << 16) | (bytes[7] << 24);
    var end = pos + dataSize;
    if (dataSize <= 0 || end > bytes.length) end = bytes.length;

    // local message type → (globalId, isLittleEndian, [{fieldNum,size,baseType}])
    final definitions = <int, _Def>{};

    while (pos < end) {
      final header = bytes[pos++];

      if (header == 0x0E) {
        // 14-byte header repetition（FIT 扩展头，跳过）
        pos += 13;
        continue;
      }

      final isCompressed = (header & 0x80) != 0;
      final isDefinition = !isCompressed && (header & 0x40) != 0;
      final hasDevData = !isCompressed && (header & 0x20) != 0;
      final localId = isCompressed ? ((header >> 5) & 0x03) : (header & 0x0F);

      if (isDefinition) {
        if (pos + 6 > bytes.length) break;
        final reserved = bytes[pos++];
        if (reserved != 0) break;
        final arch = bytes[pos++];
        if (arch != 0 && arch != 1) break;
        final le = arch == 0;
        if (pos + 3 > bytes.length) break;
        final globalId = _u16(bytes, pos, le);
        pos += 2;
        final fieldCount = bytes[pos++];
        final fields = <_Field>[];
        var fieldBytes = 0;
        for (var i = 0; i < fieldCount; i++) {
          if (pos + 3 > bytes.length) return _result(localTs, actTs, sessionStart);
          final num = bytes[pos++];
          final fsize = bytes[pos++];
          final btype = bytes[pos++];
          fields.add(_Field(num, fsize, btype));
          fieldBytes += fsize;
        }
        var devSize = 0;
        if (hasDevData) {
          if (pos >= bytes.length) break;
          final devCount = bytes[pos++];
          for (var i = 0; i < devCount; i++) {
            if (pos + 3 > bytes.length) return _result(localTs, actTs, sessionStart);
            // 每个 developer field 是 3 字节：(field_number, size, developer_index)
            pos++; // field number
            devSize += bytes[pos++]; // size
            pos++; // developer index
          }
        }
        definitions[localId] = _Def(globalId, le, fields, fieldBytes, devSize);
        continue;
      }

      // ---- data message ----
      final def = definitions[localId];
      if (def == null) {
        // 无从得知长度，无法安全继续；停止扫描，返回已得结果
        break;
      }

      var offset = pos;
      if (isCompressed) {
        // 压缩时间戳帧只有 1 字节时间戳，其余字段沿用定义
        offset += 1;
      }

      if (def.globalId == _msgActivity) {
        for (final f in def.fields) {
          if (f.num == 5 && f.size == 4 && offset + 4 <= bytes.length) {
            localTs ??= _fitTime(_u32(bytes, offset, def.le));
          } else if (f.num == 253 && f.size == 4 && offset + 4 <= bytes.length) {
            actTs ??= _fitTime(_u32(bytes, offset, def.le));
          }
          offset += f.size;
        }
      } else if (def.globalId == _msgSession) {
        for (final f in def.fields) {
          if (f.num == 2 && f.size == 4 && offset + 4 <= bytes.length) {
            sessionStart ??= _fitTime(_u32(bytes, offset, def.le));
          }
          offset += f.size;
        }
      } else {
        offset += def.fieldBytes;
      }
      pos = offset + def.devSize;

      // 三个值都拿到了就提前结束
      if (localTs != null && actTs != null && sessionStart != null) break;
    }
  } catch (_) {
    // 补充读取是「尽力而为」，失败一律静默降级
  }

  return _result(localTs, actTs, sessionStart);
}

class _Def {
  const _Def(
    this.globalId,
    this.le,
    this.fields,
    this.fieldBytes,
    this.devSize,
  );
  final int globalId;
  final bool le;
  final List<_Field> fields;

  /// 所有字段 size 之和（不含 developer 字段）。
  final int fieldBytes;

  /// developer 字段数据区总字节数。
  final int devSize;
}

/// 构造返回值（提前退出时复用）。
FitSupplement _result(DateTime? lt, DateTime? at, DateTime? ss) =>
    FitSupplement(
      localTimestamp: lt,
      activityTimestamp: at,
      sessionStartTime: ss,
    );

class _Field {
  const _Field(this.num, this.size, this.baseType);
  final int num;
  final int size;
  final int baseType;
}

int _u16(Uint8List b, int p, bool le) => le
    ? (b[p] | (b[p + 1] << 8))
    : ((b[p] << 8) | b[p + 1]);

int _u32(Uint8List b, int p, bool le) => le
    ? (b[p] | (b[p + 1] << 8) | (b[p + 2] << 16) | (b[p + 3] << 24))
    : ((b[p] << 24) | (b[p + 1] << 16) | (b[p + 2] << 8) | b[p + 3]);

/// FIT 时间戳 → UTC DateTime
DateTime _fitTime(int fitSeconds) {
  final unix = fitSeconds + kFitEpochUnixSeconds;
  return DateTime.fromMillisecondsSinceEpoch(unix * 1000, isUtc: true);
}
