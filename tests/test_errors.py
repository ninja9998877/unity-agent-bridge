# -*- coding: utf-8 -*-
"""给 bridge.py 单元测试错误码体系（不需要 Unity 在跑）。"""
import io
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

P = os.path.join('tools', 'errors.py')
SRC = io.open(os.path.join('tools', 'bridge.py'), 'rb').read().decode('utf-8')

# 从 bridge.py 里切出错误码相关段落，验证它们的独立行为
need = ['ERROR_CODES = {', 'def code_help(', 'def classify_error(', 'class BridgeError(',
        'def annotate(', 'SESSION_TEXT_LIMIT']

for n in need:
    assert n in SRC, 'bridge.py 里找不到: ' + n
print('bridge.py 里 6 段都在 ✓')

# 直接把 bridge.py 当模块导入（它只依赖标准库；main 在 __main__ 保护里）
print('以模块方式导入 bridge.py ...')
sys.path.insert(0, 'tools')
import bridge  # noqa: E402

fails = []


def check(name, cond, detail=''):
    if cond:
        print('  ✓ %s' % name)
    else:
        print('  ✗ %s %s' % (name, detail))
        fails.append(name)


print('\n--- code_help ---')
t, h = bridge.code_help('ZB-ACT-001')
check('已知码有标题', t == '找不到类型', repr(t))
check('已知码有提示', bool(h))
check('未知码返回 (None, None)', bridge.code_help('ZB-XXX-999') == (None, None))

print('\n--- classify_error ---')
cases = [
    ('找不到类型: LoginManager', 'ZB-ACT-001'),
    ('类型未找到（HeroSelectPanel）', 'ZB-ACT-001'),
    ('布阵面板没打开', 'ZB-ACT-004'),
    ('未进入播放模式', 'ZB-ACT-005'),
    ('LevelManagerBattle.instance 为空', 'ZB-ACT-003'),
    ('找不到 LevelManagerBattle', 'ZB-ACT-001'),
    ('找不到 towerId=1234', 'ZB-ACT-006'),
]
for text, want in cases:
    got = bridge.classify_error(text)
    check('%-42s -> %s' % (text, want), got == want, 'got %r' % got)

check('空输入返回 None', bridge.classify_error('') is None)
check('None 返回 None', bridge.classify_error(None) is None)
check('认不出的文本不瞎猜', bridge.classify_error('今天天气不错') is None,
      repr(bridge.classify_error('今天天气不错')))
check('已带码的原样返回',
      bridge.classify_error('失败 [ZB-ACT-002] 找不到成员') == 'ZB-ACT-002')

print('\n--- annotate（关键：state.ok=false 要被识别为失败）---')
r = bridge.annotate({'ok': True, 'state': {'ok': False, 'error': '找不到类型: X'}})
check('外层 ok=true + state.ok=false → ok 变 False', r['ok'] is False, repr(r))
check('  并且附加了错误码', r.get('code') == 'ZB-ACT-001', repr(r.get('code')))

r = bridge.annotate({'ok': True, 'state': {'ok': True}})
check('内外都 ok 的结果原样保留', r.get('ok') is True and 'code' not in r)

r = bridge.annotate({'ok': False, 'error': '超时'})
check('外层失败的也加码（超时不归类则只保持 False）', r['ok'] is False, repr(r))

r = bridge.annotate({'ok': False, 'error': '找不到类型: X'})
check('外层失败按文案归类', r.get('code') == 'ZB-ACT-001', repr(r.get('code')))

check('非 dict 输入原样返回', bridge.annotate(None) is None)
check('非 dict 输入原样返回(list)', bridge.annotate([1]) == [1])

print('\n--- BridgeError ---')
e = bridge.BridgeError('ZB-ACT-001', '找不到类型: Foo')
check('str 带码和标题', 'ZB-ACT-001' in str(e) and '找不到类型' in str(e), str(e))
check('str 带处理建议', 'probe' in str(e), str(e))
d = e.to_dict()
check('to_dict 有 code/message/title/hint',
      all(k in d for k in ('code', 'message', 'title', 'hint')), repr(d))

e2 = bridge.BridgeError('ZB-XXX-999', 'x')
check('未知码不崩', e2.to_dict()['code'] == 'ZB-XXX-999')
check('未知码 str 有「失败」兜底', '失败' in str(e2), str(e2))

print('\n--- 错误码表完整性 ---')
codes = list(bridge.ERROR_CODES)
check('码数 >= 20', len(codes) >= 20, str(len(codes)))
check('全部符合 ZB-XXX-NNN 格式',
      all(__import__('re').fullmatch(r'ZB-(CLI|BRIDGE|ACT)-\d{3}', c) for c in codes),
      str([c for c in codes if not __import__('re').fullmatch(r'ZB-(CLI|BRIDGE|ACT)-\d{3}', c)]))
check('每条都有标题和处理建议',
      all(isinstance(v, tuple) and len(v) == 2 and v[0] and v[1]
          for v in bridge.ERROR_CODES.values()),
      str([k for k, v in bridge.ERROR_CODES.items() if not (isinstance(v, tuple) and len(v) == 2 and v[0] and v[1])]))

print()
if fails:
    print('失败 %d 项: %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('全部通过 ✓')
