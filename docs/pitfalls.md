# 坑

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

## 2. 播放模式下 Unity **不会重新编译脚本**

改完 `BridgeActions.cs` 后发指令，如果当时正在播放模式，新 action 不会被认出来
（Unity 不会在 Play 模式下做脚本重编译）。

**对策**：`stop` → 等编译完 → 再 `play`。

```bash
python tools/bridge.py send stop
sleep 15                                    # 等编译
python tools/bridge.py send play
python tools/bridge.py actions              # 确认新 action 出现了
```

写自动化脚本时，`stop` 之后固定等 15~25 秒比较稳（大工程首次编译更久）。

---

## 3. 读到了上一轮的陈旧结果

如果外部只写 `cmd` 文件、不清理 `result` 文件，而 Unity 这次响应很慢，
就可能读到上一次的 `result`，误以为指令已执行。

**对策**：`bridge.py` 每次 `send` 前**先删掉 `result` 文件**，再写 `cmd`。
自己实现时务必照做。

---

## 4. 写指令文件写了一半，Unity 就读了

外部进程正在写 `cmd` 文件时，Unity 的轮询可能刚好读到**写了一半的 JSON**，解析失败。

**对策**：**原子写** —— 先写临时文件再改名。

```python
with open(path + ".tmp", "w", encoding="utf-8") as f:
    f.write(text)
os.replace(path + ".tmp", path)     # 同一文件系统上的改名是原子的
```

Unity 侧解析失败也不该崩溃，返回 `{"ok": false, "error": "..."}` 即可。

---

## 5. 同一条指令被执行两次

`cmd` 文件如果读完不删，下一次轮询会再执行一遍 ——
如果是 `play` 或发消息这类动作，后果就很难看。

**对策**：**读完立刻删**（本项目的 `AgentBridge.Update()` 就是这么做的）。

---

## 6. `Temp/` 目录可能不存在

工程从没打开过时，`Temp/` 还没生成，写文件会失败。

**对策**：写之前确保目录存在；`bridge.py` 会检查并给出明确报错。

---

## 7. Windows 控制台中文乱码

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

## 8. 编辑器日志在哪

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

## 9. Batchmode 和编辑器不能同时开

同一工程被两个 Unity 实例打开会直接崩（`HandleProjectAlreadyOpenInAnotherInstance`），
报错信息很长，容易误判成"Unity 坏了"。

**对策**：跑 batchmode（编译校验 / EditMode 测试）前先确认编辑器已关。
