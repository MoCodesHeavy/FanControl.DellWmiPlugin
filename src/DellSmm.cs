using System;
using System.Management;

namespace FanControl.DellWmiPlugin
{
    /// <summary>
    /// Sends Dell SMM BIOS commands through the ACPI-WMI "LegacyDiags" interface
    /// (root\dcim\sysman\diagnostics). This is the same backend the Linux
    /// dell-smm-hwmon driver uses on machines without the legacy I/O-port SMM handler.
    /// </summary>
    internal sealed class DellSmm : IDisposable
    {
        public const uint GetFanState   = 0x00a3;
        public const uint SetFanState   = 0x01a3;
        public const uint GetFanSpeed   = 0x02a3;
        public const uint GetNomSpeed   = 0x04a3;
        public const uint GetTemp       = 0x10a3;
        public const uint GetTempType   = 0x11a3;
        public const uint GetSignature1 = 0xfea3;
        public const uint GetSignature2 = 0xffa3;

        // Manual/automatic fan control pair confirmed on the Latitude 5540
        // (also used by the Linux driver for the Latitude 7320/7530).
        public const uint DisableAutoFan = 0x30a3;
        public const uint EnableAutoFan  = 0x31a3;

        private const string Namespace = @"root\dcim\sysman\diagnostics";
        private const string ClassName = "LegacyDiags";

        private readonly object _lock = new object();
        private ManagementObject _instance;

        public static DellSmm Open()
        {
            var scope = new ManagementScope(Namespace);
            scope.Connect();
            using (var searcher = new ManagementObjectSearcher(scope, new ObjectQuery("SELECT * FROM " + ClassName)))
            using (var results = searcher.Get())
            {
                foreach (ManagementObject mo in results)
                    return new DellSmm { _instance = mo };
            }
            throw new InvalidOperationException("No " + ClassName + " instance found in " + Namespace + ".");
        }

        /// <summary>
        /// Performs one SMM call. Returns false if the BIOS rejected the command
        /// (same rules as the Linux driver: eax unchanged or low word 0xFFFF).
        /// </summary>
        public bool TryCall(uint eax, uint ebx, out uint eaxOut, out uint edxOut)
        {
            eaxOut = 0;
            edxOut = 0;
            lock (_lock)
            {
                var obj = _instance;
                if (obj == null)
                    return false;

                using (ManagementBaseObject inParams = obj.GetMethodParameters("Execute"))
                {
                    inParams["EaxLen"] = 4u;
                    inParams["EaxVal"] = BitConverter.GetBytes(eax);
                    inParams["EbxLen"] = 4u;
                    inParams["EbxVal"] = BitConverter.GetBytes(ebx);
                    inParams["EcxLen"] = 4u;
                    inParams["EcxVal"] = BitConverter.GetBytes(0u);
                    inParams["EdxLen"] = 4u;
                    inParams["EdxVal"] = BitConverter.GetBytes(0u);

                    using (ManagementBaseObject outParams = obj.InvokeMethod("Execute", inParams, null))
                    {
                        if (outParams == null)
                            return false;
                        eaxOut = ReadReg(outParams["EaxVal"]);
                        edxOut = ReadReg(outParams["EdxVal"]);
                    }
                }
            }

            if (eaxOut == eax || (eaxOut & 0xFFFF) == 0xFFFF)
                return false;
            return true;
        }

        public bool TryCall(uint eax, uint ebx, out uint eaxOut)
        {
            uint edx;
            return TryCall(eax, ebx, out eaxOut, out edx);
        }

        public bool VerifySignature()
        {
            foreach (var cmd in new[] { GetSignature1, GetSignature2 })
            {
                uint eax, edx;
                if (TryCall(cmd, 0, out eax, out edx) && eax == 0x44494147u && edx == 0x44454C4Cu) // "DIAG" / "DELL"
                    return true;
            }
            return false;
        }

        private static uint ReadReg(object value)
        {
            var bytes = value as byte[];
            if (bytes == null || bytes.Length == 0)
                return 0;
            var buf = new byte[4];
            Array.Copy(bytes, buf, Math.Min(4, bytes.Length));
            return BitConverter.ToUInt32(buf, 0);
        }

        public void Dispose()
        {
            lock (_lock)
            {
                if (_instance != null)
                {
                    _instance.Dispose();
                    _instance = null;
                }
            }
        }
    }
}
