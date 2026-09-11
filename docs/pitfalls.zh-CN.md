# 坑

[English](pitfalls.md) | [简体中文](pitfalls.zh-CN.md)

按"踩到的痛苦程度"排序。第一条是最容易误判的。

---

## 1. ⚡ 编辑器失焦 → 播放循环**完全停摆**

### 现象

游戏启动后卡在某个加载步骤不动，进度条 0%，没有任何报错。
**看起来像网络连不上、资源下载失败、或者死锁。**

### 真相

Unity 编辑器一旦失去 OS 焦点，**播放循环彻底不走帧**——不是降速，是完全停止。

实测数据（Unity 2020.3，Windows）：

| | `Time.frameCount` |
|---|---|
| 失焦后 115 秒内 | **2**（一动不动） |
| 重新聚焦后 6 秒 | 203 |
| 再 6 秒 | 628 |

### 为什么后果这么严重

很多系统的异步推进都挂在 `MonoBehaviour.Update()` 上：

- 资源框架的驱动器（例如 YooAsset 的 `YooAssetsDriver` → `OperationSystem.Update()`）
- 自己写的协程调度、定时器
- 网络回调轮询

帧循环一停，这些**全部不推进**。资源加载操作永远停在进行中，
于是表现成"卡在加载页"，和网络问题的表象一模一样。

**文件驱动的 agent 天然处于失焦状态**（谁的焦点在终端上），所以必踩这个坑。

### 两个反直觉点（都实测过）

| 你以为 | 实际 |
|---|---|
| `PlayerSettings.runInBackground = true` 能解决 | ❌ **对编辑器播放循环无效** |
| `Application.isFocused` 能判断有没有焦点 | ❌ **失焦时它仍返回 `true`** |

### 对策

`play` 动作已内置：置位 `AutoFocus` → 播放模式下检测帧号 2 秒不涨就调
`SetForegroundWindow` 把编辑器拉回前台。`stop` 时关闭，不影响手动按 Play。

自己实现的话，Windows 上就是：

```csharp
[DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hWnd);
[DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

var h = Process.GetCurrentProcess().MainWindowHandle;
ShowWindow(h, 9);        // SW_RESTORE
SetForegroundWindow(h);
```

### 排查口诀

> **卡住了，先量循环活没活，别猜网络。**

```bash
python tools/bridge.py send frame      # 隔几秒再发一次，比对 frameCount
```

- 在涨 → 循环正常，是真·逻辑问题，去读日志
- 不涨 → 循环被挂起，**此时看到的一切"异常"都是假象**

---

## 2. 原生模态框会把编辑器**整个卡住**，桥完全没响应

Unity 弹出**原生模态框**时（最常见的是场景脏了之后的 **「Save Changes?」**），**编辑器会整个冻住**，
桥完全不再响应 —— 每一条指令都只是超时。

从外面看，这和"Unity 卡死了""网络慢"一模一样，**极易白等很久**（我为此浪费了大量时间）。
它是独立的 Win32 `#32770` 窗口，**看一眼屏幕就能立刻发现**。

**对策** —— 工具自带：

```bash
python tools/bridge.py unblock
# {"ok":true,"dismissed":1,"clicked":"Don't Save"}
```

它会找到这类对话框，只点**非提交**按钮（「不保存」/「否」/「取消」）—— **绝不点「保存」**，
那会写你的工程文件（场景、Prefab）。`send` 在超时后也会自动跑一次这个检查。

> 仅 Windows（用 Win32 `EnumWindows` + `BM_CLICK`）。脚本文件必须存成 **UTF-8 with BOM**，
> 否则 PowerShell 5.1 按 ANSI 读会乱码报错。

### 这个框到底是谁弹的

**别默认是 Unity 内置的，先 grep 自己的工程：**

```bash
grep -rn "DisplayDialog\|SaveCurrentModifiedScenesIfUserWantsTo\|SaveOpenScenes" Assets/
```

工程里很常见有人自己在播放模式钩子里加了个「Save Changes?」提示 —— 于是**每次**播放都弹，
每次都把你的自动化卡死。这种地方的修法**不是删掉它**（人要用的），
而是给它一个跳过开关，由驱动方在进播放模式前置位。

### 场景脏标记是**清不掉**的

很容易想到："那我在播放前把 `Scene.isDirty` 重置掉，不就永远不弹了？"
**没有这个 API。** 在 Unity 2020.3 上用反射把真实成员打出来验证过：

| | 结论 |
|---|---|
| `Scene.isDirty` | **只有 getter** —— 没有 setter，连 internal 的都没有 |
| `Scene.GetIsDirtyInternal` | static、**非 public**，且只读 |
| `EditorSceneManager` | 只有 `MarkSceneDirty` / `MarkAllScenesDirty` —— **只能置脏，不能清** |

所以只能靠"保存"或"重新加载场景"来清，别在这上面浪费时间。**优先用跳过开关，而不是想办法清脏。**

> **不要凭记忆猜 API 长什么样 —— 反射打出来看真实成员。**
> 一个 20 行的探针 action 就把「试到能编译为止」变成了确定答案。

**通用规则：超过一分钟没有任何反馈，就去看屏幕，不要接着等。**

---

## 3. Unity 不会在你以为的时候重新编译 —— 而且编译失败时会偷偷用**旧程序集**

两个相关的坑，本质都是「你在跑的代码」和「你以为在跑的代码」不一致。

### 2a. 播放模式下不重编译

改完 `BridgeActions.cs` 后发指令，如果当时正在播放模式，新 action 不会被认出来
（Unity 不会在 Play 模式下做脚本重编译）。

### 2b. 编译失败时，Unity 继续用**上一次成功**的程序集

这个危险得多。C# 编译失败时，Unity 会保留**上一次编译成功**的程序集继续运行，于是：

- 所有 action 照常响应
- 桥看起来完全健康
- **但你驱动的是旧代码，拿到的每一个结果都是假成功**

回包里没有任何东西会告诉你这件事。你可能长时间以为某个修改生效了，其实它根本没被加载。

### 对策

**不要在每个脚本里自己搓** —— 工具自带：

```bash
python tools/bridge.py compile      # 等编译结束、打印错误、失败时退出码非 0
```

```
编译失败 ✗ —— Unity 仍在用上一次成功的程序集运行，此时驱动得到的是旧代码的结果。
  Assets/Editor/MyActions.cs(578,18): error CS1001: Identifier expected
```

`send` 默认也带守卫：编译失败时**拒绝发送**，而不是把旧结果给你（`--no-guard` 可关）。
两者底层都是 `compile_status` action，用 `EditorUtility.scriptCompilationFailed` 判断，
返回 `{isCompiling, compilationFailed, ready}`。

完整的重编译周期：

```bash
python tools/bridge.py send stop
sleep 15                            # 让 Unity 重编译
python tools/bridge.py compile      # 通过才继续，不通过就别驱动
python tools/bridge.py send play
```

> **如果编译压根没启动**，多半是编辑器没注意到文件变化。把编辑器窗口切到前台 ——
> Unity 在获得焦点时才会刷新资源。（和坑 1 同源：失焦的编辑器比你以为的"少干很多活"。）

---

## 4. 读到了上一轮的陈旧结果

如果外部只写 `cmd` 文件、不清理 `result` 文件，而 Unity 这次响应很慢，
就可能读到上一次的 `result`，误以为指令已执行。

**对策**：`bridge.py` 每次 `send` 前**先删掉 `result` 文件**，再写 `cmd`。
自己实现时务必照做。

---

## 5. 写指令文件写了一半，Unity 就读了

外部进程正在写 `cmd` 文件时，Unity 的轮询可能刚好读到**写了一半的 JSON**，解析失败。

**对策**：**原子写** —— 先写临时文件再改名。

```python
with open(path + ".tmp", "w", encoding="utf-8") as f:
    f.write(text)
os.replace(path + ".tmp", path)     # 同一文件系统上的改名是原子的
```

Unity 侧解析失败也不该崩溃，返回 `{"ok": false, "error": "..."}` 即可。

---

## 6. 同一条指令被执行两次

`cmd` 文件如果读完不删，下一次轮询会再执行一遍 ——
如果是 `play` 或发消息这类动作，后果就很难看。

**对策**：**读完立刻删**（本项目的 `AgentBridge.Update()` 就是这么做的）。

---

## 7. `Temp/` 目录可能不存在

工程从没打开过时，`Temp/` 还没生成，写文件会失败。

**对策**：写之前确保目录存在；`bridge.py` 会检查并给出明确报错。

---

## 8. Windows 控制台中文乱码

Python 在 Windows 上默认用 GBK 输出，中文日志变乱码。

**对策**：

```python
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
```

（`bridge.py` 已内置。）

---

## 9. 编辑器日志在哪

排查问题基本都要读它：

| 平台 | 路径 |
|---|---|
| Windows | `%LOCALAPPDATA%\Unity\Editor\Editor.log` |
| macOS | `~/Library/Logs/Unity/Editor.log` |
| Linux | `~/.config/unity3d/Editor.log` |

```bash
python tools/bridge.py log --tail 100
python tools/bridge.py log --tail 50 --grep "你的 TAG"
```

> 注意：如果用团结引擎（Tuanjie）等衍生版本，日志路径不同，
> 需要手动 `--path` 指定。

---

## 10. Batchmode 和编辑器不能同时开

同一工程被两个 Unity 实例打开会直接崩（`HandleProjectAlreadyOpenInAnotherInstance`），
报错信息很长，容易误判成"Unity 坏了"。

**对策**：跑 batchmode（编译校验 / EditMode 测试）前先确认编辑器已关。
