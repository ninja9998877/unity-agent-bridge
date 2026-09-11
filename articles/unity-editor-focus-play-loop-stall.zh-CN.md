# Unity 编辑器失焦后，游戏就停摆了：一个把我引向错误方向的坑

> 游戏卡在加载页 0%，不报错、不崩溃、网络日志一堆超时。
> 我花了很久往网络和资源上查 —— 方向全错。
> 真正的原因只有一句话：**Unity 编辑器失去焦点时，播放循环会完全停摆。**

---

## 现象：一个"看起来像网络问题"的死局

一个 Unity 手游项目，编辑器里按 Play 启动。进度条走到某一步就停住了：

```
正在连接服务器...   0.0%
```

没有异常、没有崩溃、Console 里连个红字都没有。同时日志里在反复刷：

```
Curl error 28: Failed to connect to 10.x.x.x port 8880 after 21029 ms: Timed out
```

这看起来还能是什么？网络不通呗。

于是我按网络问题查了一轮：

- 确认那个地址通不通 → 不通
- 查这个地址是谁 → 原来是**打点统计服**，不是登录服
- 确认真正的登录服 → 通的

**打点服不可达只是噪音，它压根不挡登录。** 这个发现排除了一个错误方向，
但游戏还是卡着。

---

## 转折：一句"焦点不在 Unity 上"

真正把我拉回正轨的，是同事随口一句：**"焦点没有在 Unity，我发现它不走逻辑了。"**

我当时的第一反应是"不至于吧"——失焦最多降帧，怎么会不走逻辑？

但这句话值得验证。于是往桥接层加了一个探针，把 `Time.frameCount` 读出来：

```csharp
[BridgeAction("frame")]
public static JObject Frame()
{
    return new JObject
    {
        ["isPlaying"]     = Application.isPlaying,
        ["frameCount"]    = Time.frameCount,
        ["time"]          = Math.Round(Time.realtimeSinceStartup, 2),
        ["runInBackground"] = Application.runInBackground,
        ["isFocused"]     = Application.isFocused,
        ["editorPaused"]  = EditorApplication.isPaused,
    };
}
```

隔几秒发一次，比对 `frameCount`。结果很干脆：

| 时刻 | `frameCount` | `Time.realtimeSinceStartup` |
|---|---|---|
| 失焦期间（115 秒内多次采样） | **2** | 21 → 115 |
| 重新聚焦后 6 秒 | 203 | 123.7 |
| 再 6 秒 | 628 | 130.8 |

**115 秒，走了 2 帧。**

不是降速，不是卡顿，是**彻底停摆**。`realtimeSinceStartup` 在涨，说明编辑器主线程活着，
但播放循环一帧都不推进。

---

## 为什么后果这么严重

如果只是"画面不动"，那还好办 —— 一眼就能看出来。

真正麻烦的是：**大量异步系统都挂在 `MonoBehaviour.Update()` 上**。

以资源框架为例（YooAsset，Unity 里很常用）：

```
YooAssetsDriver.Update()          ← 一个挂在 GameObject 上的 MonoBehaviour
  └─ YooAssets.Update()
       └─ OperationSystem.Update()   ← 所有异步操作在这里推进
```

帧循环一停，`OperationSystem.Update()` 就不再被调用，
于是**资源初始化操作永远处于"进行中"**。

这就是为什么它表现得像网络问题：加载进度条停在 0%，
和"资源下载卡住"的表象一模一样。**但网络其实一点问题都没有。**

对做编辑器自动化的人来说这更致命：**文件驱动的 agent 天然处于失焦状态**
（人的焦点在终端上），所以必踩，而且每次都会踩。

---

## 两个反直觉的地方

### 1. `PlayerSettings.runInBackground = true` 对这个没用

直觉上，既然失焦会停，那打开"后台运行"不就行了？

我实测过：**在编辑器里无效**。运行时 `Application.runInBackground` 明明是 `true`，
帧循环照样停。

（`runInBackground` 是给**打包后的 player** 用的。编辑器播放循环的挂起是另一回事。）

### 2. `Application.isFocused` 不可靠

更不能信的是这个 —— **失焦时它仍然返回 `true`**。

上面那张表里，`frameCount` 冻在 2 的那几次采样，`isFocused` 全报 `true`。
所以**不能用它来判断"我是不是失焦了"**。

---

## 对策：自己把窗口抢回前台

既然只有"真的聚焦"才行，那就主动聚焦。

Windows 上就是两个 Win32 API：

```csharp
[DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hWnd);
[DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

public static bool FocusEditorWindow()
{
    var h = System.Diagnostics.Process.GetCurrentProcess().MainWindowHandle;
    if (h == IntPtr.Zero) return false;
    ShowWindow(h, 9);          // SW_RESTORE
    return SetForegroundWindow(h);
}
```

然后做成**自动的**：播放模式下，如果帧号 2 秒没涨，就抢一次焦点。

```csharp
private static int _lastFrame = -1;
private static double _lastFrameChangeAt;

private static void KeepLoopAlive()
{
    if (!AutoFocus || !Application.isPlaying) return;

    double now = EditorApplication.timeSinceStartup;
    if (Time.frameCount != _lastFrame)
    {
        _lastFrame = Time.frameCount;
        _lastFrameChangeAt = now;
    }
    else if (now - _lastFrameChangeAt > 2.0)
    {
        FocusEditorWindow();
        _lastFrameChangeAt = now;   // 失败也 2 秒后再试，不刷屏
    }
}
```

只在"播放中且帧号停滞"时触发，所以**手动按 Play 时不会来抢你的焦点**。

---

## 更普遍的教训：卡住了，先量循环活没活

这个坑最贵的地方不是它本身，而是**它把你引向完全错误的方向**。
你会去查网络、查 CDN、查资源版本、查服务器 —— 全都不是。

所以现在我的排查顺序是：

> **卡住了 → 先发两次 `frame` 比对 `frameCount`。**

- 在涨 → 循环正常，是**逻辑问题**，安心去读日志
- 不动 → **循环被挂起了**（失焦 / 暂停 / 正在编译）。
  **此时你看到的一切"异常"都是假象**，包括那些超时和报错

最后这条很关键。日志里的报错**不一定**是病因。
我们那次刷屏的 `Curl error 28` 就是完全无关的打点超时 —— 如果先入为主地顺着它查，
就会在一个不存在的"网络问题"上耗掉半天。

---

## 这个坑顺带促成了什么

因为要反复验证，我干脆做了个小工具：让 AI agent 通过文件协议驱动 Unity 编辑器 ——
把游戏开到指定状态、读回运行时数据，形成「复现 → 读日志 → 定位 → 改 → 再复现」的闭环。

关键设计是 **agent 自己加接口**：不预置一堆 API，而是让它在遇到具体问题时，
读代码搞清"这个现场正常玩是怎么走到的"，然后写一个最直达的方法。
加一个方法就是一个新能力，编译后立刻可用。

```
① 读代码      → 搞清「怎样才能到达那个现场」
② 加 action   → 写一个最直达的方法
③ 编译        → 几秒
④ 驱动        → 把游戏开到目标状态
⑤ 读状态+日志 → 定位
⑥ 改代码 → 回到 ③
⑦ 跑通了      → 把这条链路存下来复用
```

那条"失焦停摆"的坑，也直接变成了工具里的一个内置对策（就是上面那段自动抢焦点）。

仓库在这里：**https://github.com/ninja9998877/unity-agent-bridge**（MIT）

---

## 一句话总结

> **Unity 编辑器失去 OS 焦点时，播放循环会完全停摆 —— 不是降速。**
> 所有靠 `MonoBehaviour.Update` 驱动的异步系统会一起卡死，表象极像网络问题。
> 而且 `runInBackground` 挡不住、`isFocused` 还会骗你。

下次遇到"卡在加载页、又不报错"，先别查网络，**先量帧号**。

---

*实测环境：Unity 2020.3.33f1 / Windows 11。不同版本与平台的表现可能不同，
如果你在别的版本上复现不出，欢迎告诉我 —— 这个行为值得一张更完整的对照表。*
