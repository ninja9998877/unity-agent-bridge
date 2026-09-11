# Recipes: saving and reusing chains

[English](recipes.md) | [简体中文](recipes.zh-CN.md)

**Every time a chain works, save it.** Don't make the next repro start from zero —
re-walking the warm-up steps (login, pick a server, navigate into a screen) every single time is pure waste.

---

## Saving

The `session` log automatically records **every `send`** (action + args + whether it succeeded).

```bash
python tools/bridge.py session clear          # clear before starting a new repro
python tools/bridge.py send play
python tools/bridge.py send login --arg account=test01 --arg password=xxx
python tools/bridge.py send select_server --arg serverId=1001
python tools/bridge.py send enter_battle --arg battleId=100001

python tools/bridge.py recipe save my-flow    # keeps only steps with ok=true
```

The generated `tools/recipes/my-flow.json`:

```json
{
  "name": "my-flow",
  "description": "generated from the session log (4 steps)",
  "steps": [
    { "action": "play" },
    { "action": "login", "args": { "account": "test01", "password": "xxx" } },
    { "action": "select_server", "args": { "serverId": 1001 } },
    { "action": "enter_battle", "args": { "battleId": 100001 } }
  ]
}
```

> ⚠️ The generated file is a **minimal working version** — it only guarantees the steps and
> arguments are right. Hand-edit it to add `wait` / `expect` / variables (see below).

---

## Replaying

```bash
# whole chain
python tools/bridge.py recipe run my-flow

# only the tail (reuse part of the chain)
python tools/bridge.py recipe run my-flow --from 3

# only one step
python tools/bridge.py recipe run my-flow --only 2

# keep going after failures (see the whole picture in one pass)
python tools/bridge.py recipe run my-flow --keep-going
```

`--from` is the key to "reuse only part of the chain". If the first two steps are login
(which you only need once a day) and the interesting part is the battle that follows,
you'd normally run `--from 3` and jump straight to it.

---

## Variable substitution

**Don't hard-code accounts and passwords in a recipe.** Use `${VAR}`:

```json
{
  "name": "my-flow",
  "vars": { "ACCOUNT": "test01" },
  "steps": [
    { "action": "login", "args": { "account": "${ACCOUNT}", "password": "${PASSWORD}" } }
  ]
}
```

Resolution order: `--var` > the recipe's `vars` > environment variables.

```bash
python tools/bridge.py recipe run my-flow --var ACCOUNT=test02
PASSWORD=xxx python tools/bridge.py recipe run my-flow
```

> If the *entire* value is a single `${VAR}`, the original type is preserved (numbers stay numbers).
> Embedded in a larger string (e.g. `"user_${ID}"`) it's concatenated as text.

---

## Conditional waits

Many steps need to wait for a state change. Use `expect`: **trigger first, then poll until the condition holds.**

```json
{
  "action": "play",
  "expect": {
    "action": "editor_info",
    "args": {},
    "path": "state.isPlaying",
    "equals": true,
    "timeout": 30
  }
}
```

| Field | Meaning |
|---|---|
| `action` | **The action used for polling — it must be read-only** (calling it repeatedly must have no side effects) |
| `args` | Arguments passed while polling |
| `path` | Path into the result, e.g. `state.curState`, `state.scenes.0` |
| `equals` | Expected value (compared as strings) |
| `timeout` | Seconds before giving up, default 60 |

For a simple fixed wait, use `wait` (seconds):

```json
{ "action": "select_server", "args": { "serverId": 1001 }, "wait": 5 }
```

`label` gives a step a human-readable name, printed during replay:

```json
{ "action": "enter_battle", "args": { "battleId": 100001 }, "label": "enter battle 100001" }
```

---

## A complete example

```json
{
  "name": "enter-battle",
  "description": "login → pick server → main city → enter a specific battle (fixed seed for reproducibility)",
  "vars": { "ACCOUNT": "test01", "SERVER": 1001 },
  "steps": [
    {
      "action": "play",
      "label": "enter play mode",
      "expect": { "action": "editor_info", "path": "state.isPlaying", "equals": true, "timeout": 60 }
    },
    {
      "action": "login",
      "args": { "account": "${ACCOUNT}", "password": "${PASSWORD}" },
      "label": "log in"
    },
    {
      "action": "select_server",
      "args": { "serverId": "${SERVER}" },
      "label": "pick server, enter main city",
      "expect": { "action": "game_state", "path": "state.curState", "equals": "CITY", "timeout": 90 }
    },
    {
      "action": "enter_battle",
      "args": { "battleId": 100001, "seed": 12345 },
      "label": "enter battle (seed 12345)",
      "expect": { "action": "game_state", "path": "state.curState", "equals": "BATTLE", "timeout": 60 }
    }
  ]
}
```

---

## ⚠️ Recipes are private assets

A recipe typically contains **accounts, passwords, server IDs and internal business flows**.
**Don't commit them to a public repo.**

The upstream `.gitignore` already ignores `tools/recipes/*.json` by default.
You can also keep recipes entirely outside the repo:

```bash
python tools/bridge.py --recipe-dir /path/to/private-recipes recipe run my-flow
```
