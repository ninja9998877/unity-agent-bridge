# -*- coding: utf-8 -*-
"""验证轮询退避：结果很快到达时，send() 不该还在硬等。

不需要 Unity —— 起一个后台线程，几十毫秒后把结果文件写出来，
模拟「Unity 已经写完」的情形。旧实现固定 sleep 0.2s，所以无论结果
多早到，都要等满一个周期；新实现应该几乎立刻返回。
"""
import io
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


tmp = tempfile.mkdtemp(prefix='bridgetest_')
try:
    os.makedirs(os.path.join(tmp, 'Temp'))
    b = bridge.Bridge(tmp, 'testbridge', timeout=5.0)

    def write_result_after(delay, action='ping'):
        def _w():
            time.sleep(delay)
            data = {'ok': True, 'action': action, 'state': {'pong': True}}
            with open(b.result_path, 'w', encoding='utf-8') as f:
                json.dump(data, f)
        t = threading.Thread(target=_w, daemon=True)
        t.start()
        return t

    print('--- 结果 30ms 后到达 ---')
    t = write_result_after(0.03)
    t0 = time.time()
    r = b.send('ping', record=False, quiet=True)
    el = time.time() - t0
    check('拿到了结果', r is not None and r.get('ok') is True, repr(r))
    print('    耗时 %.3fs' % el)
    # 旧实现固定 sleep 0.2s，最少也要 0.2s 才返回
    check('比旧的 0.2s 周期更快（<0.15s）', el < 0.15, '%.3fs' % el)
    check('动作标记被 annotate 保留', r.get('action') == 'ping', repr(r.get('action')))

    print('\n--- 结果 5ms 后到达（最快的情形）---')
    t = write_result_after(0.005)
    t0 = time.time()
    r = b.send('ping', record=False, quiet=True)
    el2 = time.time() - t0
    check('拿到了结果', r is not None and r.get('ok') is True, repr(r))
    print('    耗时 %.3fs' % el2)
    check('首轮就命中（<0.06s）', el2 < 0.06, '%.3fs' % el2)

    print('\n--- 陈旧结果（action 不匹配）应被丢弃 ---')
    # 先放一条别的 action 的结果
    with open(b.result_path, 'w', encoding='utf-8') as f:
        json.dump({'ok': True, 'action': 'pong', 'state': {'stale': True}}, f)
    t = write_result_after(0.05, action='ping')
    t0 = time.time()
    r = b.send('ping', record=False, quiet=True)
    el3 = time.time() - t0
    check('丢弃陈旧结果并等到自己的', r is not None and r.get('action') == 'ping', repr(r))
    print('    耗时 %.3fs' % el3)
    check('没有白等到超时（<0.5s）', el3 < 0.5, '%.3fs' % el3)

    print('\n--- wait_for 首次即命中的延迟 ---')
    # send() 每次都会先删掉结果文件再发指令，所以「只写一次」会被下一轮删掉。
    # 这里让写入端持续写一小段时间，模拟 Unity 每次都及时回包。
    stop = threading.Event()

    def keep_writing():
        while not stop.is_set():
            with open(b.result_path, 'w', encoding='utf-8') as f:
                json.dump({'ok': True, 'action': 'state', 'state': {'pong': True}}, f)
            time.sleep(0.005)

    t = threading.Thread(target=keep_writing, daemon=True)
    t.start()
    t0 = time.time()
    # ⚠ 路径要带 state 前缀：wait_for 是对整条返回结果取路径（recipe 里写的
    #   也是 state.xxx），不是对 state 内部取。
    ok, last = b.wait_for('state', {}, 'state.pong', 'True', timeout=5.0)
    el4 = time.time() - t0
    stop.set()
    check('wait_for 命中', ok is True, repr(last))
    print('    耗时 %.3fs' % el4)
    check('比旧的 1.0s 周期快得多（<0.3s）', el4 < 0.3, '%.3fs' % el4)

finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n--- 间隔序列 ---')
d = bridge.POLL_MIN
seq = []
for _ in range(8):
    seq.append(round(d, 3))
    d = bridge.next_poll_delay(d)
print('  send   :', seq)
check('从 POLL_MIN 起', seq[0] == bridge.POLL_MIN, seq[0])
check('封顶 POLL_MAX', max(seq) == bridge.POLL_MAX, max(seq))
check('单调不减', all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)), seq)

w = bridge.POLL_WAIT_MIN
seqw = []
for _ in range(6):
    seqw.append(round(w, 2))
    w = bridge.next_poll_delay(w, bridge.POLL_WAIT_MIN, bridge.POLL_WAIT_MAX)
print('  wait   :', seqw)
check('wait_for 封顶 POLL_WAIT_MAX', max(seqw) == bridge.POLL_WAIT_MAX, max(seqw))

print()
if fails:
    print('失败 %d 项: %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('全部通过 ✓')
