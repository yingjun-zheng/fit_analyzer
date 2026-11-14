"""验证 fit_supplement.dart 的算法（逐行等价移植），比对 fitparse 金标准。

用途：Dart 代码在 Flutter SDK 就绪前无法编译验证，先用 Python 等价实现
     证明「FIT 扫描算法 + 字段号 + 纪元换算」全部正确。
"""
import glob
import os
import struct
import sys

import fitparse

FIT_EPOCH_UNIX = 631065600
MSG_ACTIVITY = 34
MSG_SESSION = 18

D = r'C:\Users\zhengyingjun\Desktop\history\码表fit数据'


def u16(b, p, le):
    return struct.unpack_from('<H' if le else '>H', b, p)[0]


def u32(b, p, le):
    return struct.unpack_from('<I' if le else '>I', b, p)[0]


def fit_time(sec):
    return sec + FIT_EPOCH_UNIX


def read_supplement(bytes_):
    local_ts = act_ts = session_start = None
    b = bytes_
    if len(b) < 14:
        return None, None, None
    header_size = b[0]
    if header_size < 12 or header_size > len(b):
        return None, None, None
    pos = header_size
    data_size = u32(b, 4, True)
    end = pos + data_size
    if data_size <= 0 or end > len(b):
        end = len(b)

    definitions = {}
    while pos < end:
        header = b[pos]
        pos += 1
        if header == 0x0E:
            pos += 13
            continue
        is_def = (header & 0x40) != 0 and (header & 0x80) == 0
        has_dev = (header & 0x20) != 0 and (header & 0x80) == 0
        is_compressed = (header & 0x80) != 0
        local_id = ((header >> 5) & 0x03) if is_compressed else (header & 0x0F)

        if is_def:
            reserved = b[pos]; pos += 1
            if reserved != 0:
                break
            arch = b[pos]; pos += 1
            if arch not in (0, 1):
                break
            le = arch == 0
            gid = u16(b, pos, le); pos += 2
            fcount = b[pos]; pos += 1
            fields = []
            for _ in range(fcount):
                fn = b[pos]; fs = b[pos + 1]; bt = b[pos + 2]; pos += 3
                fields.append((fn, fs, bt))
            dev_size_accum = 0
            if has_dev:
                dcount = b[pos]; pos += 1
                for _ in range(dcount):
                    # 每个 developer field 是 3 字节：(field_number, size, developer_index)
                    pos += 1                  # field number
                    dev_size_accum += b[pos]  # size
                    pos += 1                  # size
                    pos += 1                  # developer index
            # 与 Dart 保持一致：非目标消息也记录（用于跳过数据帧）
            definitions[local_id] = (gid, le, fields, dev_size_accum)
            continue

        d = definitions.get(local_id)
        if d is None:
            break
        gid, le, fields, dev_size = d
        offset = pos + (1 if is_compressed else 0)
        if gid == MSG_ACTIVITY:
            for (fn, fs, bt) in fields:
                if fn == 5 and fs == 4 and local_ts is None:
                    local_ts = fit_time(u32(b, offset, le))
                elif fn == 253 and fs == 4 and act_ts is None:
                    act_ts = fit_time(u32(b, offset, le))
                offset += fs
        elif gid == MSG_SESSION:
            for (fn, fs, bt) in fields:
                if fn == 2 and fs == 4 and session_start is None:
                    session_start = fit_time(u32(b, offset, le))
                offset += fs
        else:
            for (fn, fs, bt) in fields:
                offset += fs
        # ⚠️ developer 字段的数据区也必须跳过，否则流会失步
        pos = offset + dev_size
        if pos > len(b):
            break
        if local_ts is not None and act_ts is not None and session_start is not None:
            break
    return local_ts, act_ts, session_start


def main():
    files = sorted(glob.glob(os.path.join(D, '*.fit')))
    ok = bad = 0
    for fp in files:
        raw = open(fp, 'rb').read()
        lt, at, ss = read_supplement(raw)

        f = fitparse.FitFile(fp)
        acts = list(f.get_messages('activity'))
        sess = list(f.get_messages('session'))
        gold_lt = acts[0].get_value('local_timestamp') if acts else None
        gold_at = acts[0].get_value('timestamp') if acts else None
        gold_ss = sess[0].get_value('start_time') if sess else None

        my_lt = _dt(lt); my_at = _dt(at); my_ss = _dt(ss)
        m1 = _eq(my_lt, gold_lt); m2 = _eq(my_at, gold_at); m3 = _eq(my_ss, gold_ss)
        status = 'OK ' if (m1 and m2 and m3) else 'FAIL'
        if status == 'OK ':
            ok += 1
        else:
            bad += 1
        print(f'{status} {os.path.basename(fp)}')
        if status != 'OK ':
            print(f'      local_ts  mine={my_lt} gold={gold_lt} {m1}')
            print(f'      act_ts    mine={my_at} gold={gold_at} {m2}')
            print(f'      sess.start mine={my_ss} gold={gold_ss} {m3}')
        else:
            off = None
            if my_lt and my_at:
                off = int((my_lt - my_at).total_seconds())
            print(f'      local={my_lt} act={my_at} sess={my_ss} offset={off}')
    print(f'\n==== {ok} OK / {bad} FAIL (total {len(files)}) ====')
    return 0 if bad == 0 else 1


def _dt(unix):
    if unix is None:
        return None
    import datetime
    return datetime.datetime.fromtimestamp(unix, datetime.timezone.utc).replace(tzinfo=None)


def _eq(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b).total_seconds() < 1e-6


if __name__ == '__main__':
    sys.exit(main())
