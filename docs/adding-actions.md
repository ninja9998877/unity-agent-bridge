# Adding actions

[English](adding-actions.md) | [简体中文](adding-actions.zh-CN.md)

> This is the core usage of the whole toolkit. The framework only provides a skeleton —
> **capabilities grow on the spot, as you hit problems.**

---

## The mindset: read the code first, then write the action

Before adding an action you must answer one question:

> **How does the game *normally* get to this state?**

The answer can only come from reading the code. Find the entry method on that path and call it directly.

**Don't guess.** A guessed path lands you in a state that *looks* right but isn't.
Bugs reproduced and conclusions drawn in that state are all wrong — **worse than never arriving.**

> This is also why *you* write the action instead of picking from a fixed menu: the states worth
> reaching are only discoverable by reading this specific codebase.

---

## Four places to find the real path

### 1. The project's own developer tools (fastest)

Many projects ship a debug panel: fast login, level skip, grant item, scene switch.
They've **already found the shortest path** — just copy how they call it.

```csharp
// A fast-login panel in the project probably looks like this:
Type t = typeof(LoginManager);
MethodInfo m = t.GetMethod("AccountLogin", BindingFlags.NonPublic | BindingFlags.Instance);
m.Invoke(LoginManager.GetInstance(), new object[] { account, password });
```

The upside: **no need to modify business code** (those debug methods are often private),
and the path is guaranteed correct.

### 2. A UI button's OnClick handler

Whatever the button calls is the entry point of the normal flow. Follow it down a few levels
to find the method that actually does the work.

### 3. State machine transitions

Methods like `SetState(State.Battle)` usually prepare the UI, the data and the scene in one shot —
excellent entry points.

### 4. Protocol send functions

For "send a request, server pushes something back" flows (e.g. sending a chat command that
triggers a battle), just call the protocol sender and let the server do the rest.

---

## Writing the action

```csharp
/// <summary>Account login in one step, without going through the login screen</summary>
[BridgeAction("login")]
public static JObject Login(string account, string password)
{
    var mgr = GetLoginManager();
    if (mgr == null) return Error("not at the login screen yet");

    CallPrivate(mgr, "AccountLogin", account, password);

    return new JObject
    {
        ["ok"] = true,
        ["account"] = account,
        ["hint"] = "login started, check the server list in a moment",
    };
}
```

### Checklist

| | |
|---|---|
| Signature | `public static JObject` |
| Attribute | `[BridgeAction("name")]`, name in snake_case |
| Naming | `verb_object`: `login`, `select_server`, `enter_battle`, `set_hero_level` |
| Params | `int` / `float` / `bool` / `string`, names matching `--arg k=v` |
| Granularity | **Straight to the point** — reach the target state directly |
| Return | Include whatever you'll assert on |
| Randomness | **Must accept a seed** |
| Failure | Return `{"ok": false, "error": "..."}` — don't throw |

---

## On random seeds (easiest to skip, worst to skip)

With randomness involved, an unfixed seed means the bug **won't reproduce at all**:

```csharp
[BridgeAction("enter_battle")]
public static JObject EnterBattle(int battleId, int seed = 0)
{
    if (seed != 0)
    {
        // Find whatever drives the battle RNG and fix it.
        // Common shapes: UnityEngine.Random.InitState(seed) / a custom RandomUtil.SetSeed(seed)
        InitBattleRandom(seed);
    }
    ...
}
```

On the first repro attempt, try a few seeds until one triggers it, **record it in the recipe**,
and from then on it's deterministic.

---

## What state to return

The return value is your only reliable assertion basis. **Err on the side of more**, especially:

- Numeric: HP, gold, level, round, countdown
- Lists: buffs, party members, unlocks
- State machine: current state, current scene, current panel name
- Counts: how many of something

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

**Don't** return just `{"ok": true}` — that leaves you guessing from screenshots and logs,
which throws away most of the value.

---

## Anti-patterns

### ✗ Simulating clicks

```csharp
[BridgeAction("click_login")]                  // don't
public static JObject ClickLogin() { /* simulate a click */ }
```

That belongs to OS-level automation (screenshot + coordinate clicking).
Simulating clicks inside the editor is **slow and brittle** (any layout change breaks it)
and throws away the biggest advantage here — going straight there.

### ✗ Forcing state in

```csharp
[BridgeAction("fake_battle")]                  // don't
public static JObject FakeBattle() { battle = new Battle(); ... }   // bypasses the real entry flow
```

State constructed by bypassing the business path **isn't a state that ever occurs in production**.
Bugs reproduced that way are fake, and fixing them accomplishes nothing.

### ✗ A generic reflection invoker

```csharp
[BridgeAction("invoke")]                       // don't
public static JObject Invoke(string type, string method, JArray args) { ... }
```

It looks like it can "do anything", but the real consequences are: unauditable (nobody knows
what the agent called), unreusable (one-off calls can't be captured in a recipe), and unreviewable
(code review can't see the intent).

**Writing every capability out explicitly is the design position of this tool.**

---

## Where project-specific actions go

`BridgeActions.cs` holds **generic capabilities only** (nothing game-specific).
Put project-specific actions in a separate file:

```
Assets/Editor/AgentBridge/
├── AgentBridge.cs            # skeleton, don't touch
├── BridgeActions.cs          # generic capabilities (upgradable from upstream)
└── ProjectBridgeActions.cs   # ← your project-specific actions, not open-sourced
```

`namespace AgentBridge` + `[BridgeAction]` is all it takes to be discovered — no registration.

The benefit of splitting: **generic capabilities can be upgraded independently, and project
content stays cleanly in a private repo.**
