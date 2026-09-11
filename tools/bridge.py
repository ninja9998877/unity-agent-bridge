#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bridge.py —— 从命令行驱动 Unity 编辑器里的 AgentBridge。

AgentBridge 在 Unity 侧监听一个指令文件、回写一个结果文件（详见 docs/architecture.md）。
这个脚本把那套文件协议包装成好用的命令行，并额外提供：

  * 每一步都记进 session 日志
  * 把一条**跑通过**的链路存成 recipe，以后可整条或分段复用

只依赖 Python 标准库，无第三方包。

用法示例：
    python bridge.py actions
    python bridge.py send ping
    python bridge.py send probe --arg type=GameStateManager --arg member=curState --arg via=Instance
    python bridge.py recipe run recipes/enter-battle.json --var ACCOUNT=test01
    python bridge.py recipe save my-flow
    python bridge.py log --tail 80
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RECIPE_DIR = os.path.join(HERE, "recipes")

# Windows 控制台默认不是 UTF-8，中文输出会乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# 缺省约定：可用 --project / 环境变量覆盖
ENV_PROJECT = "AGENTBRIDGE_PROJECT"
ENV_PREFIX = "AGENTBRIDGE_PREFIX"


# ─────────────────────────────────────────────────────────────────────
# 基础工具
# ─────────────────────────────────────────────────────────────────────

def die(msg, code=1):
    print("[bridge] 错误: %s" % msg, file=sys.stderr)
    sys.exit(code)


def info(msg):
    print("[bridge] %s" % msg, file=sys.stderr)


def editor_log_path():
    """Unity 编辑器日志的默认位置（按平台）"""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "Unity", "Editor", "Editor.log")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Logs/Unity/Editor.log")
    return os.path.expanduser("~/.config/unity3d/Editor.log")


def write_atomic(path, text):
    """先写临时文件再替换，避免 Unity 读到写了一半的指令"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def parse_arg_pairs(pairs):
    """--arg k=v → {"k": "v"}，自动把数字/bool 还原成 JSON 类型"""
    out = {}
    for item in pairs or []:
        if "=" not in item:
            die("--arg 需要 k=v 形式，收到: %s" % item)
        k, v = item.split("=", 1)
        out[k.strip()] = coerce(v)
    return out


def coerce(v):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def dig(obj, path):
    """按 "state.foo.bar" 取值，取不到返回 None"""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
    return cur


# ─────────────────────────────────────────────────────────────────────
# 桥接客户端
# ─────────────────────────────────────────────────────────────────────

class Bridge(object):
    def __init__(self, project, prefix, timeout):
        self.project = os.path.abspath(project)
        self.prefix = prefix
        self.timeout = timeout
        self.temp = os.path.join(self.project, "Temp")
        self.cmd_path = os.path.join(self.temp, prefix + "_cmd.json")
        self.result_path = os.path.join(self.temp, prefix + "_result.json")
        self.session_path = os.path.join(self.temp, prefix + "_session.jsonl")

        if not os.path.isdir(self.temp):
            die("找不到 %s —— --project 指向的是 Unity 工程根目录吗？" % self.temp)

    # ---------- 核心收发 ----------

    def send(self, action, args=None, timeout=None, record=True, quiet=False):
        """发一条指令并等结果。返回结果 dict；超时返回 None。"""
        timeout = timeout if timeout is not None else self.timeout

        # 清掉上一轮结果，避免读到陈旧数据
        if os.path.exists(self.result_path):
            try:
                os.remove(self.result_path)
            except OSError:
                pass

        write_atomic(self.cmd_path, json.dumps(
            {"action": action, "args": args or {}}, ensure_ascii=False))

        deadline = time.time() + timeout
        result = None
        while time.time() < deadline:
            if os.path.exists(self.result_path):
                try:
                    with open(self.result_path, "r", encoding="utf-8") as f:
                        result = json.load(f)
                    break
                except (ValueError, OSError):
                    pass          # 还没写完，下一轮再读
            time.sleep(0.2)

        if result is None:
            if not quiet:
                info("超时 %ss 未收到结果：action=%s" % (timeout, action))
            return None

        if record:
            self._record(action, args or {}, result)
        return result

    def _record(self, action, args, result):
        """把每一步落进 session 日志 —— recipe save 就是从它生成"""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "action": action,
            "args": args,
            "ok": bool(result.get("ok")),
        }
        try:
            with open(self.session_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def session(self):
        if not os.path.exists(self.session_path):
            return []
        out = []
        with open(self.session_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        return out

    def clear_session(self):
        if os.path.exists(self.session_path):
            os.remove(self.session_path)

    # ---------- 语义化等待 ----------

    def wait_for(self, poll_action, poll_args, path, equals, timeout):
        """反复调 poll_action，直到 dig(result, path) == equals"""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.send(poll_action, poll_args, record=False, quiet=True)
            if last is not None:
                got = dig(last, path)
                if got is not None and str(got) == str(equals):
                    return True, last
            time.sleep(1.0)
        return False, last


# ─────────────────────────────────────────────────────────────────────
# recipe
# ─────────────────────────────────────────────────────────────────────

VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def substitute(value, variables):
    """对 args 里的字符串做 ${VAR} 替换；整串就是一个变量时保留原类型"""
    if isinstance(value, str):
        m = VAR_RE.fullmatch(value.strip())
        if m:
            return variables.get(m.group(1), value)
        return VAR_RE.sub(lambda m: str(variables.get(m.group(1), m.group(0))), value)
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    return value


def recipe_path(name_or_path, recipe_dir=None):
    if os.path.isfile(name_or_path):
        return name_or_path
    base = recipe_dir or DEFAULT_RECIPE_DIR
    for cand in (name_or_path, name_or_path + ".json"):
        p = os.path.join(base, cand)
        if os.path.isfile(p):
            return p
    die("找不到 recipe: %s（也不在 %s 下）" % (name_or_path, base))


def load_recipe(name_or_path, recipe_dir=None):
    path = recipe_path(name_or_path, recipe_dir)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "steps" not in data or not isinstance(data["steps"], list):
        die("recipe 缺少 steps 数组: %s" % path)
    return path, data


def cmd_recipe_run(bridge, args):
    path, recipe = load_recipe(args.name, args.recipe_dir)

    variables = {}
    variables.update({k: v for k, v in (recipe.get("vars") or {}).items()})
    variables.update(parse_arg_pairs(args.var))
    # 环境变量兜底（例如口令不写进 recipe）
    for key in list(VAR_RE.findall(json.dumps(recipe, ensure_ascii=False))):
        if key not in variables and key in os.environ:
            variables[key] = os.environ[key]

    steps = recipe["steps"]
    total = len(steps)

    # --from / --only 用来「只复用链路里的某几段」
    if args.only is not None:
        picked = [args.only]
    else:
        start = args.__dict__.get("from_step") or 1
        picked = list(range(start, total + 1))

    info("执行 recipe: %s（共 %d 步%s）" % (
        recipe.get("name", path), total,
        "" if len(picked) == total else "，本次执行 " + ",".join(map(str, picked))))

    failed = 0
    for idx in picked:
        if idx < 1 or idx > total:
            die("步骤编号越界: %s（共 %d 步）" % (idx, total))
        step = steps[idx - 1]
        action = step.get("action")
        if not action:
            die("第 %d 步缺少 action 字段" % idx)

        step_args = substitute(step.get("args") or {}, variables)
        label = step.get("label") or action
        print("\n── [%d/%d] %s" % (idx, total, label))

        expect = step.get("expect")
        if expect:
            # 带期望的步骤：先触发，再轮询到满足为止
            trigger = bridge.send(action, step_args)
            if trigger is None or not trigger.get("ok"):
                print("   ✗ 触发失败: %s" % json.dumps(trigger, ensure_ascii=False)[:300])
                failed += 1
                if not args.keep_going:
                    break
                continue

            poll_action = expect.get("action", "editor_info")
            poll_args = substitute(expect.get("args") or {}, variables)
            ok, last = bridge.wait_for(
                poll_action, poll_args, expect["path"], expect["equals"],
                expect.get("timeout", 60))
            if ok:
                print("   ✓ 已满足 %s == %s" % (expect["path"], expect["equals"]))
            else:
                print("   ✗ 超时：%s 未达到 %s（当前 %s）" % (
                    expect["path"], expect["equals"],
                    dig(last, expect["path"]) if last else "无结果"))
                failed += 1
                if not args.keep_going:
                    break
        else:
            result = bridge.send(action, step_args)
            if result is None:
                print("   ✗ 无响应（Unity 那边是不是没开 / 没编译完？）")
                failed += 1
                if not args.keep_going:
                    break
                continue
            print("   %s %s" % ("✓" if result.get("ok") else "✗",
                                json.dumps(result, ensure_ascii=False)[:400]))
            if not result.get("ok"):
                failed += 1
                if not args.keep_going:
                    break

        if step.get("wait"):
            time.sleep(float(step["wait"]))

    if failed:
        info("结束：%d 步失败" % failed)
        return 1
    info("结束：全部成功 ✓")
    return 0


def cmd_recipe_save(bridge, args):
    """把 session 日志里**成功**的步骤固化成 recipe"""
    entries = [e for e in bridge.session() if e.get("ok")]
    if not entries:
        die("session 日志里没有成功的步骤，先跑通一遍再保存")

    if args.action_prefix:
        entries = [e for e in entries if e["action"].startswith(args.action_prefix)]
        if not entries:
            die("过滤后没有步骤了")

    steps = []
    for e in entries:
        step = {"action": e["action"]}
        if e.get("args"):
            step["args"] = e["args"]
        steps.append(step)

    recipe = {
        "name": args.name,
        "description": args.description or "由 session 日志生成（%d 步）" % len(steps),
        "steps": steps,
    }

    out_dir = args.recipe_dir or DEFAULT_RECIPE_DIR
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, args.name + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)

    print("已保存: %s（%d 步）" % (out, len(steps)))
    print("提示：链路里若有随机因素，请手动给相关步骤补 seed 参数；"
          "需要等待的步骤可补 wait / expect 字段。")
    return 0


def cmd_recipe_list(_bridge, args):
    out_dir = args.recipe_dir or DEFAULT_RECIPE_DIR
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(out_dir) if n.endswith(".json"))
    if not names:
        print("(还没有 recipe，跑通一遍后执行 `recipe save <名字>` 生成)")
        return 0
    for n in names:
        path = os.path.join(out_dir, n)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            print("%-28s %2d 步  %s" % (n, len(data.get("steps", [])),
                                        data.get("description", "")))
        except (ValueError, OSError):
            print("%-28s (读取失败)" % n)
    return 0


# ─────────────────────────────────────────────────────────────────────
# 编译守卫
#
# ⚡ C# 编译失败时，Unity 会继续用**上一次成功的程序集**运行 ——
#    所有 action 照常响应，但跑的是旧代码。于是驱动「成功」了，拿到的却是旧结果。
#    这是最隐蔽的一类误判，必须由工具兜住，而不是每个调用方自己记得检查。
# ─────────────────────────────────────────────────────────────────────

def recent_compile_errors(log_path=None, limit=30):
    """从 Editor.log 里取最后一次编译失败的错误行"""
    path = log_path or editor_log_path()
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    start = 0
    for i in range(len(lines) - 1, -1, -1):       # 定位最后一次编译开始
        if "Starting script compilation" in lines[i]:
            start = i
            break
    errs = [l.strip() for l in lines[start:] if "error CS" in l]
    return sorted(set(errs))[:limit]


def compile_check(bridge, timeout=60.0, log_path=None):
    """等编译结束并返回 (ok, 错误行列表)。桥不支持 compile_status 时退回只看日志。"""
    deadline = time.time() + timeout
    st = bridge.send("compile_status", record=False, quiet=True)

    if st is None or not st.get("ok"):
        # 旧版桥没有该 action —— 只能看日志，判断不了 isCompiling，尽力而为
        errs = recent_compile_errors(log_path)
        return (not errs), errs

    state = st.get("state") or {}
    while state.get("isCompiling") and time.time() < deadline:
        time.sleep(1.0)
        again = bridge.send("compile_status", record=False, quiet=True)
        if again and again.get("ok"):
            st, state = again, again.get("state") or {}

    if not state.get("compilationFailed"):
        return True, []
    return False, recent_compile_errors(log_path)


def guard_before_drive(bridge, log_path=None):
    """发送前守卫：编译失败就返回提示语，否则 None"""
    st = bridge.send("compile_status", record=False, quiet=True)
    if st is None or not st.get("ok"):
        return None                                # 桥不支持 —— 跳过守卫
    if (st.get("state") or {}).get("compilationFailed"):
        errs = recent_compile_errors(log_path)
        detail = ("\n  " + "\n  ".join(errs[:10])) if errs else ""
        return ("编译失败，拒绝驱动：Unity 仍在用上一次成功的程序集运行，"
                "此时拿到的会是旧代码的结果。" + detail)
    return None




# ─────────────────────────────────────────────────────────────────────
# 命令行
# ─────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="bridge.py",
        description="驱动 Unity 编辑器里的 AgentBridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--project", default=os.environ.get(ENV_PROJECT),
                   help="Unity 工程根目录（默认取环境变量 %s）" % ENV_PROJECT)
    p.add_argument("--prefix", default=os.environ.get(ENV_PREFIX, "agentbridge"),
                   help="指令文件前缀，默认 agentbridge")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="单条指令等待秒数，默认 60")
    p.add_argument("--recipe-dir", default=None,
                   help="recipe 存放目录（默认 tools/recipes，不同项目可用不同目录）")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("actions", help="列出 Unity 侧已注册的 action")

    sp = sub.add_parser("send", help="发一条指令")
    sp.add_argument("action")
    sp.add_argument("--arg", action="append", default=[], metavar="k=v")
    # SUPPRESS：不给就沿用全局 --timeout，不要用 None 覆盖掉
    sp.add_argument("--timeout", type=float, default=argparse.SUPPRESS)
    sp.add_argument("--no-guard", action="store_true",
                    help="跳过编译守卫（默认：编译失败时拒绝发送，避免拿到旧程序集的假结果）")

    cp = sub.add_parser("compile", help="等 Unity 编译结束并报结果；编译失败时退出码非 0")
    cp.add_argument("--timeout", type=float, default=180.0, help="等待上限秒数，默认 180")
    cp.add_argument("--log", default=None, help="手动指定 Editor.log 路径")

    sp = sub.add_parser("wait", help="反复轮询直到某个路径满足条件")
    sp.add_argument("--action", required=True, help="用来轮询的 action（应是只读的）")
    sp.add_argument("--arg", action="append", default=[], metavar="k=v")
    sp.add_argument("--path", required=True, help="结果里的路径，如 state.curState")
    sp.add_argument("--equals", required=True)
    sp.add_argument("--timeout", type=float, default=60.0)

    rec = sub.add_parser("recipe", help="链路的保存与复用").add_subparsers(
        dest="recipe_cmd", required=True)

    r = rec.add_parser("list", help="列出已有 recipe")
    r.set_defaults(func=cmd_recipe_list)

    r = rec.add_parser("run", help="执行 recipe")
    r.add_argument("name", help="recipe 名或 json 路径")
    r.add_argument("--var", action="append", default=[], metavar="k=v", help="变量替换")
    r.add_argument("--from", dest="from_step", type=int, default=1, metavar="N",
                   help="从第 N 步开始（复用链路中的某一段）")
    r.add_argument("--only", type=int, default=None, metavar="N", help="只跑第 N 步")
    r.add_argument("--keep-going", action="store_true", help="失败也继续往下跑")
    r.set_defaults(func=cmd_recipe_run)

    r = rec.add_parser("save", help="把本次 session 里成功的步骤存成 recipe")
    r.add_argument("name")
    r.add_argument("--description", default=None)
    r.add_argument("--action-prefix", default=None, help="只保留某前缀的 action")
    r.set_defaults(func=cmd_recipe_save)

    ses = sub.add_parser("session", help="查看/清空本次执行记录").add_subparsers(
        dest="session_cmd", required=True)
    ses.add_parser("show", help="显示已记录的步骤")
    ses.add_parser("clear", help="清空记录（建议开始一轮新复现前清一次）")

    lg = sub.add_parser("log", help="看 Unity 编辑器日志尾部")
    lg.add_argument("--tail", type=int, default=60)
    lg.add_argument("--grep", default=None, help="只显示匹配的行（正则）")
    lg.add_argument("--path", default=None, help="手动指定日志文件")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "log":
        path = args.path or editor_log_path()
        if not os.path.isfile(path):
            die("找不到日志: %s（用 --path 指定）" % path)
        pat = re.compile(args.grep) if args.grep else None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if pat:
            lines = [l for l in lines if pat.search(l)]
        sys.stdout.write("".join(lines[-args.tail:]))
        return 0

    if not args.project:
        die("没指定工程目录：加 --project <Unity 工程根目录>，"
            "或设环境变量 %s" % ENV_PROJECT)

    bridge = Bridge(args.project, args.prefix, args.timeout)

    if args.cmd == "actions":
        result = bridge.send("list_actions")
        if result is None:
            die("Unity 没响应。确认编辑器已打开、AgentBridge.cs 已编译（看 Console 里有没有 "
                "[AgentBridge] 已就绪）")
        if not result.get("ok"):
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        for n in result["state"]["actions"]:
            print(n)
        return 0

    if args.cmd == "send":
        if not args.no_guard:
            blocked = guard_before_drive(bridge)
            if blocked:
                die(blocked)
        result = bridge.send(args.action, parse_arg_pairs(args.arg), timeout=args.timeout)
        if result is None:
            die("超时，没收到结果")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "compile":
        ok, errs = compile_check(bridge, timeout=args.timeout, log_path=args.log)
        if ok:
            print("编译通过 ✓")
            return 0
        print("编译失败 ✗ —— Unity 仍在用上一次成功的程序集运行，"
              "此时驱动得到的是旧代码的结果。", file=sys.stderr)
        for e in errs:
            print("  " + e, file=sys.stderr)
        if not errs:
            print("  （没能从日志提取到 error CS 行，请直接看 Editor.log）", file=sys.stderr)
        return 1

    if args.cmd == "wait":
        ok, last = bridge.wait_for(args.action, parse_arg_pairs(args.arg),
                                   args.path, args.equals, args.timeout)
        print(json.dumps(last, ensure_ascii=False, indent=2) if last else "(无结果)")
        return 0 if ok else 1

    if args.cmd == "session":
        if args.session_cmd == "clear":
            bridge.clear_session()
            print("已清空 session 记录")
        else:
            for i, e in enumerate(bridge.session(), 1):
                print("%2d. %-9s %-24s %s" % (
                    i, "ok" if e.get("ok") else "FAIL",
                    e["action"], json.dumps(e.get("args") or {}, ensure_ascii=False)))
        return 0

    if args.cmd == "recipe":
        return args.func(bridge, args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
