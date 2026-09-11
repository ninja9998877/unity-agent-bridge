# Keeping the upstream repo scrubbed

[English](open-sourcing.md) | [简体中文](open-sourcing.zh-CN.md)

This repo open-sources the **capability itself**, never any specific project's business logic.
Run through this checklist before every push.

---

## What belongs upstream

- The bridge skeleton (`AgentBridge.cs`): polling, dispatch, auto-refocus
- **Generic** actions (`BridgeActions.cs`): `ping` / `play` / `stop` / `frame` / `open_scene` / `probe` …
- The driver CLI (`bridge.py`) and the recipe mechanism
- Documentation: architecture, rules for adding actions, pitfalls

The test: **would this still work verbatim in a different Unity project?**
Yes → upstream. No → project side.

---

## What must never appear upstream

| Category | Examples |
|---|---|
| Project-specific actions | `login` / `select_server` / `send_world_chat` / `game_state` |
| Business identifiers | game name, package name, server IDs, region names, internal codenames |
| Credentials | accounts, passwords, tokens, API keys |
| Internal network info | IPs, ports, domains, machine aliases |
| Business flows | gameplay names, protocol names, config table names |
| Recipes / sessions | these will inevitably contain the above |

---

## Pre-commit self-check

```bash
# 1. Confirm no project-specific actions leaked into the generic file
grep -n "BridgeAction" unity/Assets/Editor/AgentBridge/BridgeActions.cs

# 2. Search for project identifiers (substitute your own keywords)
grep -rniE "yourgame|yourpackage|yourusername" . --exclude-dir=.git

# 3. Search for internal addresses and credentials
grep -rniE "([0-9]{1,3}\.){3}[0-9]{1,3}|password|passwd|secret|token|api[_-]?key" . \
  --exclude-dir=.git --exclude=open-sourcing.md

# 4. Make sure the recipe directory only has examples
ls tools/recipes/

# 5. See exactly what would be committed
git status --short
git diff --cached --stat
```

Check 3 will match example prose in the docs — judge those by eye. The point is **not missing real credentials.**

---

## Keeping project content out of the repo

The upstream `.gitignore` ignores `tools/recipes/*.json` by default. On the project side, prefer:

```
your-unity-project/
└── Assets/Editor/AgentBridge/
    ├── AgentBridge.cs            # synced from upstream
    ├── BridgeActions.cs          # synced from upstream
    └── ProjectBridgeActions.cs   # your project-specific actions, private repo only
```

`namespace AgentBridge` + `[BridgeAction]` is all it takes to be discovered — **no registration** —
so generic and project files can be physically separated and upgraded independently.

Same for recipes: keep them outside the repo and point at them with `--recipe-dir`:

```bash
python tools/bridge.py --recipe-dir /path/to/private-recipes recipe run my-flow
```

---

## First time open-sourcing

1. Create the repo → add generic capabilities only → push
2. **Then verify again through GitHub's search**: search for the project name, search for internal IP ranges
3. If credentials were ever committed by mistake: **deleting the file isn't enough** (it's still in
   `git log`). You must rewrite history or abandon the repo and rebuild it.
