# FanControl.DellWmiPlugin

A [FanControl](https://github.com/Rem0o/FanControl.Releases) plugin for **newer Dell laptops** whose fan controls can't be reached by the built-in Dell plugin.

The built-in Dell plugin talks to the BIOS through the old I/O-port SMM interface. Many recent Dell machines no longer answer on that interface and only accept the same SMM commands over **ACPI-WMI** (the `LegacyDiags` class in `root\dcim\sysman\diagnostics`). On those machines the built-in plugin shows no fans at all. This plugin uses the WMI route instead, the same approach the Linux `dell-smm-hwmon` driver uses on modern Dells.

## What you get

- **Fan RPM** for each fan the BIOS reports
- **Fan control** per fan, paired automatically with its RPM sensor
- **BIOS temperature sensors** (CPU and board sensors)

No kernel driver is installed. Everything goes through Dell's own WMI interface.

## Tested hardware

| Model | BIOS fan levels | Status |
|---|---|---|
| Dell Latitude 5540 | Off / ~2,400 / ~4,000 RPM | Reading and control working |

Other Dell models that expose `LegacyDiags` may work. Reading RPM and temperatures is very likely to work on them. Fan **control** depends on whether the BIOS accepts the `0x30A3` / `0x31A3` manual/automatic command pair. If you test another model, please open an issue with the results.

## Requirements

- Windows 10/11
- FanControl V281 or newer (.NET 10 build)
- FanControl running **as administrator**

## Check whether your laptop is supported

Run this in an **admin PowerShell**. If it lists `LegacyDiags` with an `Execute` method, the interface is there:

```powershell
Get-CimClass -Namespace root\dcim\sysman\diagnostics -ClassName LegacyDiags | Select CimClassName, CimClassMethods
```

## Install

1. Download `FanControl.DellWmiPlugin.dll` from the [Releases](../../releases) page.
2. Close FanControl.
3. Create the folder `C:\Program Files (x86)\FanControl\Plugins\DellWmi` and copy the DLL into it.
4. Optional: move the built-in `Plugins\DellPlugin` folder out of `Plugins`. On unsupported machines it only produces errors.
5. Start FanControl as administrator.

Or, from an admin PowerShell after downloading the DLL to your Downloads folder:

```powershell
$fc = 'C:\Program Files (x86)\FanControl'
Stop-Process -Name FanControl -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory "$fc\Plugins\DellWmi" -Force | Out-Null
Copy-Item "$env:USERPROFILE\Downloads\FanControl.DellWmiPlugin.dll" "$fc\Plugins\DellWmi\" -Force
Unblock-File "$fc\Plugins\DellWmi\FanControl.DellWmiPlugin.dll"
```

If FanControl reports missing `Dell/...` sensors afterwards, those entries belong to the old plugin. Remove the old cards from your configuration.

## How fan curves map to fan levels

Dell laptop fans only run at a few fixed levels, not continuous speeds. The plugin picks the level whose nominal RPM is closest to the requested percentage of maximum RPM. On the Latitude 5540 that works out to:

| Curve output | Fan level |
|---|---|
| Below 30% | Off |
| 30–80% | Low (~2,400 RPM) |
| Above 80% | High (~4,000 RPM) |

## Safety

- **Emergency override:** if the BIOS CPU sensor reaches **95 °C**, the fan is forced to its highest level regardless of your curve.
- **Hand-back on exit:** when FanControl closes, or a control is set back to automatic, the plugin re-enables the BIOS's own fan control.
- **Sleep/resume:** if the BIOS takes control back after resume, the plugin notices within about 20 seconds and re-applies your setting.
- **Crashes:** if FanControl is killed or crashes, the fan stays at its last level until you reboot or run the restore command below.

Restore BIOS automatic fan control manually (admin PowerShell):

```powershell
$i = Get-CimInstance -Namespace root\dcim\sysman\diagnostics -ClassName LegacyDiags | Select -First 1
$b = [byte[]][BitConverter]::GetBytes([uint32]0x31a3); $z = [byte[]](0,0,0,0)
Invoke-CimMethod -InputObject $i -MethodName Execute -Arguments @{EaxLen=[uint32]4;EaxVal=$b;EbxLen=[uint32]4;EbxVal=$z;EcxLen=[uint32]4;EcxVal=$z;EdxLen=[uint32]4;EdxVal=$z} | Out-Null
```

> **Use at your own risk.** The SMM commands were reverse-engineered by the Linux community, not documented by Dell. Test on your own machine and watch temperatures at first.

## Build from source

Requires the .NET 10 SDK.

```
dotnet build src -c Release
```

The output is `src/bin/Release/net10.0/FanControl.DellWmiPlugin.dll`. The `lib` folder holds the two reference assemblies needed to compile: `FanControl.Plugins.dll` from FanControl and `System.Management.dll` from .NET. Both already ship with FanControl, so they are not copied to the output.

## Credits

- [FanControl](https://github.com/Rem0o/FanControl.Releases) by Rémi Mercier, and the original [FanControl.DellPlugin](https://github.com/Rem0o/FanControl.DellPlugin)
- The Linux [dell-smm-hwmon](https://docs.kernel.org/hwmon/dell-smm-hwmon.html) driver documentation, for the SMM command set and the WMI SMM interface

## License

MIT. See [LICENSE](LICENSE).
