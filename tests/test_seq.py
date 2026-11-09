# -*- coding: utf-8 -*-
"""验证请求序号 seq：同名 action 连发时，能分清哪条返回属于哪次请求。

背景：旧实现只能按 action 名匹配。连发两次 `open_panel` 时，第一次超时后
Unity 才写回的结果会被第二次请求当成本次结果（串包）。seq 让匹配变成精确比对。

不需要 Unity —— 用后台线程扮演 Unity 写结果。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))

import bridge  # noqa: E402

fails = []


def check(name, cond, detail=''):
    if cond:
        print('  OK  %s' % name)
    else:
        print('  FAIL %s %s' % (name, detail))
        fails.append(name)


def read_cmd_seq(b):
    """读出 send() 刚写进 cmd 文件的 seq（模拟 Unity 侧解析请求）。"""
    with open(b.cmd_path, 'r', encoding='utf-8') as f:
        return json.load(f).get('seq')


tmp = tempfile.mkdtemp(prefix='bridgeseq_')
try:
    os.makedirs(os.path.join(tmp, 'Temp'))

    print('--- cmd 文件里带递增 seq ---')
    b = bridge.Bridge(tmp, 'testbridge', timeout=5.0)

    def echo_later(delay, action, *, override_seq=None, echo_seq=True):
        def _w():
            time.sleep(delay)
            try:
                seq = read_cmd_seq(b) if echo_seq else None
            except (OSError, ValueError):
                return
            data = {'ok': True, 'action': action, 'state': {'pong': True}}
            if echo_seq and seq is not None:
                data['seq'] = seq if override_seq is None else override_seq
            with open(b.result_path, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        t = threading.Thread(target=_w, daemon=True)
        t.start()
        return t

    echo_later(0.02, 'ping')
    b.send('ping', record=False, quiet=True)
    s1 = read_cmd_seq(b)
    echo_later(0.02, 'ping')
    b.send('ping', record=False, quiet=True)
    s2 = read_cmd_seq(b)
    check('seq 从 1 开始且递增', s1 == 1 and s2 == 2, '%r %r' % (s1, s2))

    print('\n--- 同名 action、seq 对得上的结果被接受 ---')
    # ⚠ 不能先手动 b._seq += 1 再把 want 固定下来：send() 内部还会自己 +1，
    #   那样 want 会永远比实际发出的 seq 少 1。这里和真实 Unity 一样，
    #   等指令文件落盘后再读它里面的 seq。
    want = [None]

    def writer_correct():
        time.sleep(0.02)
        want[0] = read_cmd_seq(b)
        with open(b.result_path, 'w', encoding='utf-8') as f:
            json.dump({'ok': True, 'action': 'open_panel', 'seq': want[0],
                       'state': {'panel': 'Hero'}}, f)

    threading.Thread(target=writer_correct, daemon=True).start()
    r = b.send('open_panel', record=False, quiet=True)
    check('拿到结果', r is not None, repr(r))
    check('是正确那次（panel=Hero）',
          r is not None and (r.get('state') or {}).get('panel') == 'Hero', repr(r))

    print('\n--- 同名 action、seq 是别人那次的 → 必须丢弃 ---')
    # 先放一条同名但 seq 不对的陈旧结果，随后再放正确的。
    def writer_stale_then_good():
        time.sleep(0.02)
        seq = read_cmd_seq(b)
        with open(b.result_path, 'w', encoding='utf-8') as f:
            json.dump({'ok': True, 'action': 'open_panel', 'seq': seq - 1,
                       'state': {'panel': 'STALE'}}, f)
        time.sleep(0.05)
        with open(b.result_path, 'w', encoding='utf-8') as f:
            json.dump({'ok': True, 'action': 'open_panel', 'seq': seq,
                       'state': {'panel': 'Fight'}}, f)

    threading.Thread(target=writer_stale_then_good, daemon=True).start()
    r = b.send('open_panel', record=False, quiet=True)
    check('没被陈旧结果串包',
          r is not None and (r.get('state') or {}).get('panel') == 'Fight', repr(r))

    print('\n--- 旧桥不回显 seq → 退回按 action 名匹配 ---')
    b._seq += 1
    threading.Thread(target=echo_later, args=(0.02, 'state'),
                     kwargs={'echo_seq': False}, daemon=True).start()
    r = b.send('state', record=False, quiet=True)
    check('旧桥场景仍能收到结果', r is not None and r.get('action') == 'state', repr(r))

    print('\n--- 旧桥无 action 字段 → 不再盲信（必须丢弃）---')
    b._seq += 1
    def writer_no_action():
        with open(b.result_path, 'w', encoding='utf-8') as f:
            json.dump({'ok': True, 'state': {'pong': True}}, f)
    threading.Thread(target=writer_no_action, daemon=True).start()
    r = b.send('ping', timeout=0.4, record=False, quiet=True)
    check('无 action 且无 seq 的结果不会被误认', r is None, repr(r))

finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print('失败 %d 项: %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('全部通过 ✓')
