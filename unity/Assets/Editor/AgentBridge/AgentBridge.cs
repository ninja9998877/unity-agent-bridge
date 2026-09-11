using System;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace AgentBridge
{
    /// <summary>
    /// 标记一个「场景构造」方法，供 AgentBridge 按 action 名调用。
    /// 加了这个特性的方法会被自动发现，不需要注册。
    /// </summary>
    [AttributeUsage(AttributeTargets.Method)]
    public class BridgeActionAttribute : Attribute
    {
        public readonly string Name;
        public BridgeActionAttribute(string name) { Name = name; }
    }

    /// <summary>
    /// AgentBridge：让外部 AI agent 能「命令 Unity 编辑器到达指定现场并读回状态」。
    ///
    /// 【设计意图】
    /// 框架固定，场景库随问题生长。不预置一堆 API，
    /// 而是让 agent 遇到要复现的问题时，在 BridgeActions.cs 里加一个最直达现场的 action，
    /// 编译后即可用指令驱动编辑器到达该场景。
    ///
    /// 【本文件是稳定骨架，一般不需要改】——要加能力请改 BridgeActions.cs
    ///
    /// 【指令通道】（文件轮询，UI 无阻塞）
    ///   写指令:  &lt;ProjectRoot&gt;/Temp/&lt;prefix&gt;_cmd.json      {"action":"xxx","args":{...}}
    ///   读结果:  &lt;ProjectRoot&gt;/Temp/&lt;prefix&gt;_result.json   {"ok":true,"action":"...","state":{...}}
    ///
    /// 只在编辑器下编译（放在 Assets/Editor/ 下的脚本不会进正式包）。
    /// </summary>
    [InitializeOnLoad]
    public static class AgentBridge
    {
        /// <summary>指令文件名前缀。默认 agentbridge，可用环境变量 AGENTBRIDGE_PREFIX 覆盖。</summary>
        public static string Prefix =
            Environment.GetEnvironmentVariable("AGENTBRIDGE_PREFIX") is string p && !string.IsNullOrEmpty(p)
                ? p : "agentbridge";

        private const double POLL_INTERVAL = 0.5;   // 轮询间隔(秒)
        private static double _nextPoll;
        private static bool _busy;

        /// <summary>
        /// 编辑器一旦失去 OS 焦点，播放循环会「完全停摆」（实测 Time.frameCount 冻住不动）。
        /// 所有靠 MonoBehaviour.Update 驱动的异步系统（资源加载、协程、网络回调）都会一起卡死，
        /// 表象极像网络/资源问题。
        ///
        /// 注意：PlayerSettings.runInBackground 对此【无效】，Application.isFocused 也【不可靠】。
        ///
        /// 置位后：播放模式下检测到帧号 2 秒不涨，就自动把编辑器窗口拉回前台。
        /// 由 play 动作开启、stop 动作关闭，不影响手动按 Play。
        /// </summary>
        internal static bool AutoFocus;

        private static int _lastFrame = -1;
        private static double _lastFrameChangeAt;

        private static string ProjectRoot =>
            Directory.GetParent(Application.dataPath).FullName;

        private static string CmdPath => Path.Combine(ProjectRoot, "Temp", Prefix + "_cmd.json");
        private static string ResultPath => Path.Combine(ProjectRoot, "Temp", Prefix + "_result.json");

        static AgentBridge()
        {
            EditorApplication.update += Update;
            Debug.Log($"[AgentBridge] 已就绪 (prefix={Prefix})。监听: {CmdPath}");
        }

        private static void Update()
        {
            KeepLoopAlive();

            if (_busy) return;
            if (EditorApplication.timeSinceStartup < _nextPoll) return;
            _nextPoll = EditorApplication.timeSinceStartup + POLL_INTERVAL;

            if (!File.Exists(CmdPath)) return;

            string json;
            try
            {
                json = File.ReadAllText(CmdPath);
                File.Delete(CmdPath);          // 先删，避免同一条指令被执行两次
            }
            catch (IOException)
            {
                return;                        // 文件被占用，下次轮询再来
            }

            _busy = true;
            try
            {
                WriteResult(Execute(json));
            }
            finally
            {
                _busy = false;
            }
        }

        /// <summary>播放模式下若帧循环停摆（编辑器失焦），把编辑器窗口拉回前台</summary>
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
                _lastFrameChangeAt = now;   // 失败也不刷屏，2 秒后再试
            }
        }

        /// <summary>把 Unity 编辑器窗口切到前台（仅 Windows 实现）</summary>
        public static bool FocusEditorWindow()
        {
#if UNITY_EDITOR_WIN
            try
            {
                using (var proc = System.Diagnostics.Process.GetCurrentProcess())
                {
                    IntPtr h = proc.MainWindowHandle;
                    if (h == IntPtr.Zero) return false;
                    ShowWindow(h, 9);            // SW_RESTORE
                    return SetForegroundWindow(h);
                }
            }
            catch
            {
                return false;
            }
#else
            // macOS / Linux 未实现：改为让使用者保证编辑器窗口可见且在前台
            return false;
#endif
        }

#if UNITY_EDITOR_WIN
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
#endif

        private static JObject Execute(string json)
        {
            var resp = new JObject();
            try
            {
                var cmd = JObject.Parse(json);
                string action = cmd["action"]?.ToString();
                var args = cmd["args"] as JObject ?? new JObject();

                if (string.IsNullOrEmpty(action))
                {
                    resp["ok"] = false;
                    resp["error"] = "缺少 action 字段";
                    return resp;
                }

                var method = FindAction(action);
                if (method == null)
                {
                    resp["ok"] = false;
                    resp["error"] = "未知 action: " + action;
                    resp["available"] = new JArray(ListActions().Cast<object>().ToArray());
                    return resp;
                }

                var result = method.Invoke(null, BuildArgs(method, args));
                resp["ok"] = true;
                resp["action"] = action;
                resp["state"] = result as JToken ?? JValue.CreateNull();
                return resp;
            }
            catch (TargetInvocationException tie)
            {
                resp["ok"] = false;
                resp["error"] = tie.InnerException?.ToString() ?? tie.ToString();
                return resp;
            }
            catch (Exception e)
            {
                resp["ok"] = false;
                resp["error"] = e.ToString();
                return resp;
            }
        }

        /// <summary>按 action 名查找 BridgeActions 里的方法</summary>
        private static MethodInfo FindAction(string name)
        {
            var asm = Assembly.GetAssembly(typeof(AgentBridge));
            return asm.GetTypes()
                      .Where(t => t.Namespace == "AgentBridge")
                      .SelectMany(t => t.GetMethods(BindingFlags.Public | BindingFlags.Static))
                      .FirstOrDefault(m =>
                      {
                          var attr = m.GetCustomAttribute<BridgeActionAttribute>();
                          return attr != null && attr.Name == name;
                      });
        }

        internal static string[] ListActions()
        {
            var asm = Assembly.GetAssembly(typeof(AgentBridge));
            return asm.GetTypes()
                      .Where(t => t.Namespace == "AgentBridge")
                      .SelectMany(t => t.GetMethods(BindingFlags.Public | BindingFlags.Static))
                      .Select(m => m.GetCustomAttribute<BridgeActionAttribute>())
                      .Where(a => a != null)
                      .Select(a => a.Name)
                      .OrderBy(n => n)
                      .ToArray();
        }

        /// <summary>把 JSON args 按方法签名转成参数数组（支持 int/float/bool/string）</summary>
        private static object[] BuildArgs(MethodInfo method, JObject args)
        {
            var pars = method.GetParameters();
            var values = new object[pars.Length];
            for (int i = 0; i < pars.Length; i++)
            {
                var p = pars[i];
                var token = args[p.Name] ?? args[p.Name.ToLowerInvariant()];
                if (token == null || token.Type == JTokenType.Null)
                {
                    values[i] = p.HasDefaultValue ? p.DefaultValue : DefaultOf(p.ParameterType);
                    continue;
                }
                values[i] = Convert.ChangeType(token.ToString(), p.ParameterType);
            }
            return values;
        }

        private static object DefaultOf(Type t)
        {
            return t.IsValueType ? Activator.CreateInstance(t) : null;
        }

        private static void WriteResult(JObject resp)
        {
            try
            {
                File.WriteAllText(ResultPath, resp.ToString(Newtonsoft.Json.Formatting.Indented));
            }
            catch (Exception e)
            {
                Debug.LogError("[AgentBridge] 写结果失败: " + e.Message);
            }
        }
    }
}
