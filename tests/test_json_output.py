# -*- coding: utf-8 -*-
"""验证 --json：stdout 必须正好是一个可解析的 JSON 对象，且不混入人类可读文本。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, '..', 'tools', 'bridge.py')

fails = []


def check(name, cond, detail=''):
    if cond:
        print('  OK  %s' % name)
    else:
        print('  FAIL %s %s' % (name, detail))
        fails.append(name)


def run(args, cwd=None):
    """跑 bridge.py，返回 (returncode, stdout, stderr)。stdout 必须是纯 JSON。"""
    env = dict(os.environ)
    env.pop('AGENTBRIDGE_PROJECT', None)
    p = subprocess.run([sys.executable, BRIDGE] + args, capture_output=True,
                       text=True, encoding='utf-8', errors='replace',
                       timeout=60, cwd=cwd, env=env)
    return p.returncode, p.stdout, p.stderr


def as_json(stdout):
    try:
        return json.loads(stdout)
    except ValueError:
        return None


print('--- explain <code> --json ---')
rc, so, se = run(['--json', 'explain', 'ZB-ACT-001'])
d = as_json(so)
check('stdout 是合法 JSON', d is not None, repr(so[:120]))
check('含 code/title/hint', d and {'code', 'title', 'hint'} <= set(d), repr(d))
check('ok=true', d and d.get('ok') is True)

print('\n--- explain --json（全量）---')
rc, so, se = run(['--json', 'explain'])
d = as_json(so)
check('stdout 是合法 JSON', d is not None, repr(so[:120]))
check('codes 是数组且非空', d and isinstance(d.get('codes'), list) and len(d['codes']) > 0)
check('每项都有 code/title/hint',
      d and all({'code', 'title', 'hint'} <= set(x) for x in d['codes']))

print('\n--- explain 未知码 --json（应失败退出）---')
rc, so, se = run(['--json', 'explain', 'ZB-NOPE-000'])
check('非 0 退出', rc != 0, str(rc))
check('错误信息在 stderr', 'ZB-CLI-007' in se, repr(se[:100]))

print('\n--- 缺 --project --json ---')
rc, so, se = run(['--json', 'send', 'ping'])
check('非 0 退出', rc != 0, str(rc))
check('stdout 为空（不污染 JSON 解析）', so.strip() == '', repr(so[:100]))
check('错误在 stderr 且带码', 'ZB-CLI-001' in se, repr(se[:100]))

print('\n--- recipe list --json ---')
tmp = tempfile.mkdtemp(prefix='bridgejson_')
try:
    os.makedirs(os.path.join(tmp, 'Temp'))
    rc, so, se = run(['--json', '--project', tmp, 'recipe', 'list'])
    d = as_json(so)
    check('stdout 是合法 JSON', d is not None, repr(so[:120]))
    check('recipes 是数组', d and isinstance(d.get('recipes'), list), repr(d))

    # 空 session 的 stats
    rc, so, se = run(['--json', '--project', tmp, 'session', 'stats'])
    d = as_json(so)
    check('session stats 空时仍是合法 JSON', d is not None, repr(so[:120]))
    check('含 total/failed/actions',
          d and {'total', 'failed', 'actions'} <= set(d), repr(d))

    rc, so, se = run(['--json', '--project', tmp, 'session', 'tail'])
    d = as_json(so)
    check('session tail 空时仍是合法 JSON', d is not None, repr(so[:120]))
    check('含 steps', d and 'steps' in d, repr(d))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('\n--- 非 json 模式下仍是人类可读 ---')
rc, so, se = run(['explain', 'ZB-ACT-001'])
check('没有 json 模式时输出纯文本', not so.strip().startswith('{'), repr(so[:80]))
check('含码与标题', 'ZB-ACT-001' in so and '找不到类型' in so, repr(so[:80]))

print()
if fails:
    print('失败 %d 项: %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('全部通过 ✓')
