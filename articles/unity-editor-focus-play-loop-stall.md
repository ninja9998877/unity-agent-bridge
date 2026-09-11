# Unity's editor stops simulating when it loses focus — and it looks exactly like a network bug

> The game hung on a loading screen at 0%, with no exception and no crash.
> The logs were full of network timeouts, so I spent a long time debugging the network.
> All of it was wasted. The real cause is one sentence:
> **when the Unity Editor loses OS focus, the play loop stops completely.**

---

## The symptom: a deadlock that looks like a network problem

Press Play in the editor. The loading bar stops at a specific step:

```
Connecting to server...   0.0%
```

No exception. No crash. Not a single red line in the Console. Meanwhile the log keeps repeating:

```
Curl error 28: Failed to connect to 10.x.x.x port 8880 after 21029 ms: Timed out
```

What else could that be? Obviously the network, right?

So I went down that road:

- Is that address reachable? → no
- What *is* that address? → a **telemetry server**, not the login server
- Is the actual login server reachable? → yes

So the telemetry timeouts were pure noise — they never blocked login. That killed one wrong theory.
The game was still hung.

---

## The turn: "the editor isn't focused"

What actually got me back on track was a colleague mentioning offhand: *"Focus isn't on Unity — I noticed it stops running logic."*

My first reaction was "surely not" — losing focus should cost you framerate, not logic.

But it was cheap to check. I added a probe that reads `Time.frameCount`:

```csharp
[BridgeAction("frame")]
public static JObject Frame()
{
    return new JObject
    {
        ["isPlaying"]       = Application.isPlaying,
        ["frameCount"]      = Time.frameCount,
        ["time"]            = Math.Round(Time.realtimeSinceStartup, 2),
        ["runInBackground"] = Application.runInBackground,
        ["isFocused"]       = Application.isFocused,
        ["editorPaused"]    = EditorApplication.isPaused,
    };
}
```

Sent it twice, a few seconds apart, and compared `frameCount`:

| When | `frameCount` | `Time.realtimeSinceStartup` |
|---|---|---|
| While unfocused (sampled over 115s) | **2** | 21 → 115 |
| 6s after refocusing | 203 | 123.7 |
| 6s more | 628 | 130.8 |

**Two frames in 115 seconds.**

Not slow. Not stuttering. **Completely stopped.** `realtimeSinceStartup` keeps climbing, so the
editor's main thread is alive — but the play loop isn't advancing a single frame.

---

## Why the fallout is so much worse than "the picture freezes"

If the only symptom were a frozen viewport, you'd notice immediately.

The real problem is that **a lot of async machinery is driven from `MonoBehaviour.Update()`**.

Take YooAsset, a popular Unity asset framework:

```
YooAssetsDriver.Update()          ← a MonoBehaviour on a GameObject
  └─ YooAssets.Update()
       └─ OperationSystem.Update()   ← every async operation advances here
```

When the frame loop stops, `OperationSystem.Update()` stops being called, so an **asset
initialization operation stays "in progress" forever**.

That's why it presents as a network problem: the loading bar sits at 0%, looking exactly like a
stalled download. **The network was fine the whole time.**

For anyone doing editor automation this is worse still: **a file-driven agent is unfocused by
nature** (the human's focus is in the terminal), so it hits this every single time.

---

## Two counter-intuitive findings

### 1. `PlayerSettings.runInBackground = true` does not fix it

Intuitively: if losing focus stops it, just turn on "run in background"?

Measured: **it has no effect in the editor.** `Application.runInBackground` reads `true` at
runtime, and the loop still stops.

(`runInBackground` is for the **built player**. The editor play loop suspending is a separate thing.)

### 2. `Application.isFocused` lies

This one is worse — **it still returns `true` while unfocused.**

In the table above, every sample where `frameCount` was frozen at 2 reported `isFocused: true`.
So you **cannot** use it to detect the condition.

---

## The workaround: take focus back yourself

Since only real focus works, take it.

On Windows that's two Win32 calls:

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

Then make it automatic: while playing, if the frame counter hasn't moved for 2 seconds, grab focus.

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
        _lastFrameChangeAt = now;   // retry in 2s on failure; don't spam
    }
}
```

It only fires while playing *and* stalled, so it won't steal your focus when you press Play manually.

---

## The more general lesson: measure whether the loop is alive first

The expensive part of this bug isn't the bug — it's that **it points you in a completely wrong
direction.** You go debug the network, the CDN, the asset version, the server. None of it is the problem.

So my debugging order is now:

> **Something's stuck → send `frame` twice and compare `frameCount`.**

- Increasing → the loop is fine; it's a **logic problem**, go read the log with confidence
- Frozen → **the loop is suspended** (unfocused / paused / compiling).
  **Everything that looks broken right now is an illusion** — including the timeouts and errors

That last point matters. Errors in a log are **not necessarily the cause.** Our log spam was a
completely unrelated telemetry timeout. Chase it first and you lose half a day on a network
problem that doesn't exist.

---

## What this led to

Because I ended up needing to reproduce things over and over, I built a small tool: a file-protocol
bridge that lets an AI agent drive the Unity editor — put the game into a target state, read back
runtime data, and close the loop of *reproduce → read logs → locate → fix → reproduce*.

The key design choice is that **the agent writes its own actions**: rather than shipping a fixed
set of APIs, it reads the code to figure out how the game normally reaches a given state, then adds
the one method that jumps straight there. One new method is one new capability, live as soon as
Unity compiles.

```
① Read the code  → figure out how to reach the target state
② Add an action  → one straight-to-the-point method
③ Compile        → a few seconds
④ Drive          → put the game in that state
⑤ Read state+log → locate
⑥ Fix → back to ③
⑦ Chain works    → save it for replay
```

The focus-stall workaround above is one of its built-in countermeasures.

Repo: **https://github.com/ninja9998877/unity-agent-bridge** (MIT)

---

## TL;DR

> **When the Unity Editor loses OS focus, the play loop stops completely — not slows down.**
> Every async system driven by `MonoBehaviour.Update` freezes with it, and it looks exactly like a
> network problem. `runInBackground` doesn't prevent it, and `isFocused` will actively mislead you.

Next time something hangs on a loading screen with no error: **measure the frame counter before you
measure the network.**

---

*Measured on Unity 2020.3.33f1 / Windows 11. Behavior may differ across versions and platforms —
if you can't reproduce it elsewhere, I'd like to know. This deserves a proper cross-version matrix.*
