# 怎么加 action

> 这是这套工具的核心用法。工具本身只提供骨架，**能力靠遇到问题时现场生长**。

---

## 心法：先读代码，再写 action

加 action 之前，必须回答一个问题：

> **这个现场，正常玩是「怎么走到」的？**

答案只能从代码里读出来。找那条路径上的入口方法，然后直接调它。

**不要猜。** 猜出来的路径会把你带到一个"看起来对但实际不对"的状态，
在这种状态上复现的 bug、下的结论，全是错的 —— 比到不了现场更糟糕。

---

## 找真实路径的四个入口

### 1. 项目自带的开发者工具（最快）

很多项目有调试面板：快速登录、跳关、发道具、切场景。
它们**已经帮你找好了最短路径**，照抄它们的调用方式就行。

```csharp
// 项目里的快速登录面板大概长这样：
Type t = typeof(LoginManager);
MethodInfo m = t.GetMethod("AccountLogin", BindingFlags.NonPublic | BindingFlags.Instance);
m.Invoke(LoginManager.GetInstance(), new object[] { account, password });
```

照抄的好处：**不用改业务代码**（很多调试方法原本是 private），且路径一定是对的。

### 2. UI 按钮的 OnClick 处理函数

按钮点下去调了谁，那就是正常流程的入口。顺着往下看几层，找到"真正干活"的那个方法。

### 3. 状态机的状态转移

`SetState(State.Battle)` 这类方法通常一口气把 UI、数据、场景都准备好了，很适合做入口。

### 4. 协议发送函数

如果是"发个请求，服务端推回来"的流程（比如聊天发指令触发战斗），
直接调协议发送函数即可，剩下的交给服务端。

---

## 写 action

```csharp
/// <summary>账号密码登录（一步到位，不经过登录界面）</summary>
[BridgeAction("login")]
public static JObject Login(string account, string password)
{
    var mgr = GetLoginManager();
    if (mgr == null) return Error("还没到登录界面");

    CallPrivate(mgr, "AccountLogin", account, password);

    return new JObject
    {
        ["ok"] = true,
        ["account"] = account,
        ["hint"] = "已发起登录，稍后调 servers 看服务器列表",
    };
}
```

### 检查清单

| | 要求 |
|---|---|
| 签名 | `public static JObject` |
| 特性 | `[BridgeAction("名字")]`，名字用 snake_case |
| 命名 | `动词_对象`：`login`、`select_server`、`enter_battle`、`set_hero_level` |
| 参数 | `int`/`float`/`bool`/`string`，名字与 `--arg k=v` 的键对应 |
| 粒度 | **一步到位**，直达目标状态 |
| 返回 | 带上后续要断言的状态 |
| 随机 | **必须支持传种子** |
| 失败 | 返回 `{"ok": false, "error": "..."}`，别抛异常 |

---

## 关于随机种子（最容易忽略、后果最严重）

有随机的场景，不固定种子就**复现不出来**：

```csharp
[BridgeAction("enter_battle")]
public static JObject EnterBattle(int battleId, int seed = 0)
{
    if (seed != 0)
    {
        // 找到项目里控制战斗随机数的那个 Random，固定它
        // 常见形态：UnityEngine.Random.InitState(seed) / 自定义 RandomUtil.SetSeed(seed)
        InitBattleRandom(seed);
    }
    ...
}
```

第一次复现时让 agent 试几个种子，找到能触发的那个，**记进 recipe**，以后就必现了。

---

## 返回什么状态

返回值是 agent 做断言的唯一可靠依据。**宁多勿少**，尤其是：

- 数值类：血量、金币、等级、回合数、倒计时
- 列表类：buff 列表、队伍成员、已解锁项
- 状态机类：当前状态、当前场景、当前面板名
- 计数类：某个东西有几个

```csharp
return new JObject
{
    ["ok"] = true,
    ["round"] = battle.round,
    ["leftHp"] = battle.leftHp,
    ["rightHp"] = battle.rightHp,
    ["buffs"] = new JArray(battle.buffs.Select(b => new JObject
    {
        ["id"] = b.id,
        ["stack"] = b.stack,
        ["remainMs"] = b.remainMs,
    })),
};
```

**不要**只返回 `{"ok": true}` —— 那样 agent 只能靠截图和日志猜，价值大打折扣。

---

## 反模式

### ✗ 模拟点击

```csharp
[BridgeAction("click_login")]                  // 不要
public static JObject ClickLogin() { /* 模拟点一下 */ }
```

这是 OS 层自动化（截图 + 坐标点击）该干的事。
在编辑器内模拟点击，**又慢又脆**（UI 布局一变就废），还丢掉了这里最大的优势——直达。

### ✗ 硬塞状态

```csharp
[BridgeAction("fake_battle")]                  // 不要
public static JObject FakeBattle() { battle = new Battle(); ... }   // 绕过真实入场流程
```

绕过业务路径构造出来的状态，**根本不是线上会出现的状态**。
在这种状态复现的 bug 是假的，修了也没意义。

### ✗ 通用反射执行器

```csharp
[BridgeAction("invoke")]                       // 不要
public static JObject Invoke(string type, string method, JArray args) { ... }
```

看起来"什么都能干"，实际后果是：不可审计（没人知道 agent 调了什么）、
不可复用（一次性的调用串不进 recipe）、不可 review（代码评审时看不出意图）。

**每个能力都显式写出来**，就是这个工具的设计立场。

---

## 项目专属 action 放哪

`BridgeActions.cs` 只放**通用能力**（跟具体游戏无关的那些）。
项目专有的 action 另建文件：

```
Assets/Editor/AgentBridge/
├── AgentBridge.cs            # 骨架，不动
├── BridgeActions.cs          # 通用能力（可随上游升级）
└── ProjectBridgeActions.cs   # ← 你的项目专属 action，不对外开源
```

只要 `namespace AgentBridge` + `[BridgeAction]` 就会被发现，不需要注册。

这样分的好处：**通用能力可以独立升级，项目内容可以干净地留在私有仓库**。
