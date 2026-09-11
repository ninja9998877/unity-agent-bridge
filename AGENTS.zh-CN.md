# AGENTS.md — 给 AI agent 的工作规则

[English](AGENTS.md) | [简体中文](AGENTS.zh-CN.md)

你在一个 Unity 工程里工作，目标之一是**能自己到达 bug 现场**，而不是让人替你复现。

这套工具的用法和规则都在下面。**先读完再动手。**

---

## 0. 硬性规则

1. **不要模拟人的点击。** 加 action 时要「一步到位」直达现场，不是 `click(100,200)` 点过去。
   点坐标属于 OS 层自动化的活，不是这里的活。
2. **加 action 前先读代码。** 搞清"这个现场是怎么到达的"，然后照那条真实路径写。
   **猜出来的路径会把你带到错误状态，比到不了更糟。**
3. **涉及随机的场景必须支持传随机种子。** 暴击、闪避、随机目标不固定，bug 复现不出来。
4. **返回关键状态。** action 的返回值是你的断言依据，比看截图可靠得多。
5. **只加读，慎加写。** 需要"驱动"就加一个显式 action（可审计、可复用）；
   不要加通用的"执行任意方法"接口。
6. **项目专有的 action 单独放文件**，别混进 `BridgeActions.cs`——那是通用能力，要能独立升级。

---

## 1. 先确认桥是活的

```bash
python tools/bridge.py --project <Unity工程根目录> actions
```

- 列出 action = 正常
- 报"Unity 没响应" = 编辑器没开 / 脚本没编译完 / Console 里没有 `[AgentBridge] 已就绪`

`--project` 建议设成环境变量 `AGENTBRIDGE_PROJECT`。

---

## 2. 标准工作流

```
① 读代码        →  搞清「怎样才能到达那个现场」
② 加 action     →  在 BridgeActions.cs（或你自己的 actions 文件）里写一个最直达的方法
③ 编译          →  Unity 自动编译，几秒
④ 驱动          →  bridge.py send <action> --arg k=v ...
⑤ 读状态+日志   →  bridge.py send <action> / bridge.py log --tail 100
⑥ 定位 → 改代码 → 回到 ③
⑦ 跑通后        →  bridge.py recipe save <名字>   ← 把这条链路固化下来
```

---

## 3. 怎么动态加一个 action

在 `BridgeActions.cs` 里加一个方法：

```csharp
/// <summary>直接到达「某场战斗的第 N 回合」</summary>
[BridgeAction("enter_battle")]
public static JObject EnterBattle(int battleId, int round, int seed = 0)
{
    // 1. 读代码，按项目里真实的入场路径把游戏送到目标现场
    // 2. seed != 0 时固定随机，保证可复现
    // 3. 返回关键状态供断言
    return new JObject
    {
        ["ok"] = true,
        ["round"] = round,
        ["leftHp"] = ...,
        ["rightHp"] = ...,
        ["buffs"] = new JArray(...),
    };
}
```

**要求**：

| 项 | 说明 |
|---|---|
| 签名 | `public static`，返回 `JObject`（会作为 `state` 回传） |
| 参数 | 支持 `int` / `float` / `bool` / `string`；名字与指令 `args` 的键对应 |
| 注册 | 不需要注册，`[BridgeAction("名字")]` 会自动被发现 |
| 命名 | `动词_对象`：`enter_battle`、`set_hero_level`、`replay_to_round` |
| 粒度 | **一步到位**。直达目标状态，不走交互过程 |
| 返回值 | 尽量带上后续要断言的状态 |
| 随机 | **必须支持传种子** |

**不要**写这种：

```csharp
[BridgeAction("click_login_button")]      // ✗ 这是 OS 层干的事
public static JObject ClickLoginButton() { /* 模拟一次点击 */ }
```

**要**写这种：

```csharp
[BridgeAction("login_as")]                 // ✓ 直接调用真实登录路径
public static JObject LoginAs(string account, string password)
{
    // 反射或直接调用项目里真正处理登录的那个方法（照抄项目自带开发者工具的写法最稳）
}
```

> **找真实路径的小技巧**：很多项目自带开发者/调试面板（快速登录、跳关、发道具），
> 它们已经帮你找到了"最短路径"，**照抄它们的调用方式**通常是最省事也最正确的做法。

---

## 4. 排查「卡住了」

**第一步永远是量播放循环活没活**，不要一上来就往网络/资源上猜：

```bash
python tools/bridge.py send frame
# 隔几秒再发一次，比对 frameCount
```

- `frameCount` 在涨 → 循环正常，卡住是**逻辑问题**，去读日志
- `frameCount` 不动 → **循环被挂起了**（编辑器失焦 / 暂停 / 正在编译）。
  此时所有异步系统都不会推进，**看起来像的一切问题都是假象**

详细分析见 [`docs/pitfalls.md`](docs/pitfalls.md)。这是最容易误判的一类问题。

---

## 5. 复用已经跑通的链路

**每跑通一条链路，就存下来。** 不要让下一次复现从零开始。

```bash
python tools/bridge.py session clear          # 开始前清一次
# ... 正常驱动 ...
python tools/bridge.py recipe save my-flow    # 跑通后固化
python tools/bridge.py recipe run my-flow     # 以后整条回放
python tools/bridge.py recipe run my-flow --from 3   # 只复用后半段
```

保存后**建议手工补两样东西**（自动生成的部分给不了）：

1. **`wait` / `expect`** —— 哪些步骤之后需要等，等什么条件
2. **seed** —— 链路里带随机的步骤补上固定种子

模板、变量替换、条件等待的写法见 [`docs/recipes.md`](docs/recipes.md)。

**recipe 是跟项目绑定的资产，不要提交到公开仓库**（里面会带账号、服务器 ID、业务流程）。

---

## 6. 你不该做的事

- ❌ 不要为了"一步到位"就绕过真实的业务路径去硬塞状态 —— 那样复现出来的不是真 bug
- ❌ 不要加通用的 `invoke(type, method, args)` 反射接口 —— 不可审计，也无法复用
- ❌ 不要把项目专有逻辑写进 `BridgeActions.cs`
- ❌ 不要在没有 `frame` 证据的情况下断言"是网络问题 / 资源问题"
- ❌ 不要把带账号密码、内网地址、业务流程的 recipe 提交到公开仓库
