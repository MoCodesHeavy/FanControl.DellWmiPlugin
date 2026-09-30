using System;
using System.Collections.Generic;
using System.Linq;
using FanControl.Plugins;

namespace FanControl.DellWmiPlugin
{
    /// <summary>
    /// FanControl plugin for Dell machines whose SMM BIOS is only reachable over ACPI-WMI
    /// (the stock Dell plugin uses the legacy I/O-port interface, which these models lack).
    /// Exposes fan RPM, BIOS temperature sensors, and a 3-level fan control per fan.
    /// </summary>
    public sealed class DellWmiPlugin : IPlugin2, IDisposable
    {
        private const int MaxFans = 4;
        private const int MaxTemps = 10;
        private const int FanMaxState = 2;          // off / low / high (state 3 == 2 on the 5540)
        private const int FailsafeCpuTemp = 95;     // °C: force high regardless of the curve
        private const int ReassertAfterUpdates = 20; // ~20 s of persistent mismatch

        private static readonly string[] TempLabels = { "CPU", "GPU", "SODIMM", "Other", "Ambient", "Other" };

        private readonly IPluginLogger _logger;
        private DellSmm _smm;
        private readonly List<FanChannel> _fans = new List<FanChannel>();
        private readonly List<TempChannel> _temps = new List<TempChannel>();
        private TempChannel _cpuTemp;
        private bool _manualMode;
        private bool _exitHookAdded;
        private readonly object _ctl = new object();

        public DellWmiPlugin() { }

        public DellWmiPlugin(IPluginLogger logger)
        {
            _logger = logger;
        }

        public string Name => "Dell WMI";

        public void Initialize()
        {
            Close();
            try
            {
                _smm = DellSmm.Open();
                if (!_smm.VerifySignature())
                {
                    Log("Dell SMM signature not returned over WMI; plugin disabled.");
                    _smm.Dispose();
                    _smm = null;
                    return;
                }

                DetectFans();
                DetectTemps();
                Log(string.Format("Initialized: {0} fan(s), {1} temperature sensor(s).", _fans.Count, _temps.Count));

                if (!_exitHookAdded)
                {
                    AppDomain.CurrentDomain.ProcessExit += (s, e) => RestoreAuto();
                    _exitHookAdded = true;
                }
            }
            catch (Exception ex)
            {
                Log("Initialize failed: " + ex.Message);
                _smm?.Dispose();
                _smm = null;
            }
        }

        public void Load(IPluginSensorsContainer container)
        {
            if (_smm == null)
                return;

            foreach (var fan in _fans)
            {
                container.FanSensors.Add(new FanSensor(fan));
                container.ControlSensors.Add(new ControlSensor(this, fan));
            }
            foreach (var t in _temps)
                container.TempSensors.Add(new TempSensor(t));
        }

        public void Update()
        {
            if (_smm == null)
                return;

            try
            {
                foreach (var t in _temps)
                    t.Value = ReadTemp(t.Index);

                foreach (var fan in _fans)
                {
                    uint v;
                    fan.Rpm = _smm.TryCall(DellSmm.GetFanSpeed, (uint)fan.Index, out v) ? (float?)((v & 0xFFFF) * fan.Multiplier) : null;
                    fan.State = _smm.TryCall(DellSmm.GetFanState, (uint)fan.Index, out v) ? (int?)(v & 0xFF) : null;
                }

                lock (_ctl)
                    ApplyControl();
            }
            catch (Exception ex)
            {
                Log("Update failed: " + ex.Message);
            }
        }

        public void Close()
        {
            RestoreAuto();
            _fans.Clear();
            _temps.Clear();
            _cpuTemp = null;
            if (_smm != null)
            {
                _smm.Dispose();
                _smm = null;
            }
        }

        public void Dispose() => Close();

        // ---- control -------------------------------------------------------------

        internal void RequestLevel(FanChannel fan, float percent)
        {
            lock (_ctl)
            {
                fan.RequestedPercent = percent;
                fan.RequestedLevel = PercentToLevel(fan, percent);
                ApplyControl();
            }
        }

        internal void ReleaseControl(FanChannel fan)
        {
            lock (_ctl)
            {
                fan.RequestedPercent = null;
                fan.RequestedLevel = null;
                if (_fans.All(f => f.RequestedLevel == null))
                    RestoreAuto();
            }
        }

        private void ApplyControl()
        {
            if (_smm == null || _fans.All(f => f.RequestedLevel == null))
                return;

            bool failsafe = _cpuTemp != null && _cpuTemp.Value.HasValue && _cpuTemp.Value.Value >= FailsafeCpuTemp;

            foreach (var fan in _fans)
            {
                if (fan.RequestedLevel == null)
                    continue;

                int target = failsafe ? FanMaxState : fan.RequestedLevel.Value;

                if (_manualMode && fan.LastSent == target)
                {
                    // The reported state ramps toward the target over several seconds, so only treat a
                    // mismatch as "BIOS took control back" (e.g. after sleep) if it persists.
                    fan.MismatchCount = fan.State.HasValue && fan.State != target ? fan.MismatchCount + 1 : 0;
                    if (fan.MismatchCount < ReassertAfterUpdates)
                        continue;
                    _manualMode = false;
                    Log("Fan state drifted from target; re-asserting manual control.");
                }
                fan.MismatchCount = 0;

                if (!_manualMode)
                {
                    uint r;
                    if (_smm.TryCall(DellSmm.DisableAutoFan, 0, out r))
                        _manualMode = true;
                    else
                        Log("BIOS rejected disable-auto-fan command.");
                }

                uint res;
                if (_smm.TryCall(DellSmm.SetFanState, (uint)fan.Index | ((uint)target << 8), out res))
                    fan.LastSent = target;
            }
        }

        private void RestoreAuto()
        {
            lock (_ctl)
                RestoreAutoCore();
        }

        private void RestoreAutoCore()
        {
            if (!_manualMode || _smm == null)
                return;
            try
            {
                uint r;
                _smm.TryCall(DellSmm.EnableAutoFan, 0, out r);
            }
            catch { /* best effort */ }
            _manualMode = false;
            foreach (var f in _fans)
                f.LastSent = null;
        }

        private static int PercentToLevel(FanChannel fan, float percent)
        {
            percent = Math.Max(0, Math.Min(100, percent));
            if (fan.NominalRpm != null && fan.NominalRpm[FanMaxState] > 0)
            {
                // Pick the fan state whose nominal RPM is closest to the requested share of max RPM.
                float target = percent / 100f * fan.NominalRpm[FanMaxState];
                int best = 0;
                float bestDiff = float.MaxValue;
                for (int s = 0; s <= FanMaxState; s++)
                {
                    float diff = Math.Abs(fan.NominalRpm[s] - target);
                    if (diff < bestDiff) { bestDiff = diff; best = s; }
                }
                return best;
            }
            return percent < 33.34f ? 0 : percent < 66.67f ? 1 : 2;
        }

        // ---- detection -------------------------------------------------------------

        private void DetectFans()
        {
            for (int i = 0; i < MaxFans; i++)
            {
                uint v;
                if (!_smm.TryCall(DellSmm.GetFanState, (uint)i, out v))
                    continue;

                var fan = new FanChannel { Index = i, Multiplier = 30 };
                var nominal = new int[FanMaxState + 1];
                bool ok = true;
                for (int s = 0; s <= FanMaxState; s++)
                {
                    uint n;
                    if (!_smm.TryCall(DellSmm.GetNomSpeed, (uint)i | ((uint)s << 8), out n)) { ok = false; break; }
                    nominal[s] = (int)(n & 0xFFFF);
                    if (nominal[s] > 1000)
                        fan.Multiplier = 1; // same auto-detect rule as the Linux driver
                }
                if (ok)
                {
                    for (int s = 0; s <= FanMaxState; s++)
                        nominal[s] *= fan.Multiplier;
                    fan.NominalRpm = nominal;
                }
                _fans.Add(fan);
            }
        }

        private void DetectTemps()
        {
            for (int i = 0; i < MaxTemps; i++)
            {
                uint type;
                string label = null;
                if (_smm.TryCall(DellSmm.GetTempType, (uint)i, out type))
                    label = TempLabels[Math.Min((int)(type & 0xFF), TempLabels.Length - 1)];

                if (ReadTemp(i) == null && label == null)
                    continue;

                var t = new TempChannel { Index = i, Label = (label ?? "Sensor") + " " + (i + 1) };
                _temps.Add(t);
                if (_cpuTemp == null && (label == "CPU" || (label == null && i == 0)))
                    _cpuTemp = t;
            }
        }

        private float? ReadTemp(int index)
        {
            uint v;
            if (!_smm.TryCall(DellSmm.GetTemp, (uint)index, out v))
                return null;
            int t = (int)(v & 0xFF);
            if (t == 0x99)
            {
                System.Threading.Thread.Sleep(100);
                if (!_smm.TryCall(DellSmm.GetTemp, (uint)index, out v))
                    return null;
                t = (int)(v & 0xFF);
            }
            return t > 127 || t == 0 ? (float?)null : t;
        }

        private void Log(string message)
        {
            try { _logger?.Log("[Dell WMI] " + message); } catch { }
        }
    }

    internal sealed class FanChannel
    {
        public int Index;
        public int Multiplier;
        public int[] NominalRpm;
        public float? Rpm;
        public int? State;
        public float? RequestedPercent;
        public int? RequestedLevel;
        public int? LastSent;
        public int MismatchCount;
    }

    internal sealed class TempChannel
    {
        public int Index;
        public string Label;
        public float? Value;
    }

    internal sealed class FanSensor : IPluginSensor
    {
        private readonly FanChannel _fan;
        public FanSensor(FanChannel fan) { _fan = fan; }
        public string Id => "DellWmi/Fan" + (_fan.Index + 1);
        public string Name => "Dell Fan " + (_fan.Index + 1);
        public float? Value { get; private set; }
        public void Update() => Value = _fan.Rpm;
    }

    internal sealed class TempSensor : IPluginSensor
    {
        private readonly TempChannel _t;
        public TempSensor(TempChannel t) { _t = t; }
        public string Id => "DellWmi/Temp" + (_t.Index + 1);
        public string Name => "Dell " + _t.Label;
        public float? Value { get; private set; }
        public void Update() => Value = _t.Value;
    }

    internal sealed class ControlSensor : IPluginControlSensor2
    {
        private readonly DellWmiPlugin _plugin;
        private readonly FanChannel _fan;

        public ControlSensor(DellWmiPlugin plugin, FanChannel fan)
        {
            _plugin = plugin;
            _fan = fan;
        }

        public string Id => "DellWmi/Control" + (_fan.Index + 1);
        public string Name => "Dell Fan Control " + (_fan.Index + 1);
        public string PairedFanSensorId => "DellWmi/Fan" + (_fan.Index + 1);
        public float? Value { get; private set; }

        public void Update()
        {
            if (_fan.RequestedPercent.HasValue)
            {
                Value = _fan.RequestedPercent;
            }
            else if (_fan.State.HasValue && _fan.NominalRpm != null && _fan.NominalRpm[_fan.NominalRpm.Length - 1] > 0)
            {
                int s = Math.Min(_fan.State.Value, _fan.NominalRpm.Length - 1);
                Value = 100f * _fan.NominalRpm[s] / _fan.NominalRpm[_fan.NominalRpm.Length - 1];
            }
            else
            {
                Value = null;
            }
        }

        public void Set(float val) => _plugin.RequestLevel(_fan, val);
        public void Reset() => _plugin.ReleaseControl(_fan);
    }
}
