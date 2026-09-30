# vendor/ — drop proprietary Ocean Insight installers here

Ocean Insight's **OceanView**, **OmniDriver/SeaBreeze installer**, and the signed
USB driver are licensed and **not redistributable**, so they are not checked into
this repo. Put the installer you downloaded (with your institute/account access)
into this folder, then list it in `..\config.psd1` under `VendorInstallers`.

## You do NOT need anything here if you use the open-source path

The `Seabreeze` driver source (Python + `python-seabreeze` + `seabreeze_os_setup`)
installs a working USB driver on its own and is what the dashboard's hardware
backend uses (`import seabreeze.spectrometers`). Use the vendor path only if you specifically
want the OceanView GUI or the OmniDriver SDK.

## If you do use a vendor installer

1. Download it from Ocean Insight (e.g. `OceanView-2.0.x-win64.exe`) and copy it here.
2. Find its silent-install switch (OceanView is an install4j package; `-q` is the
   usual unattended flag, optionally `-dir "C:\Program Files\Ocean Optics\OceanView"`).
   When unsure, run it once interactively and note the working flags.
3. Add an entry in `config.psd1`:

   ```powershell
   VendorInstallers = @(
       @{ File = 'OceanView-2.0.8-win64.exe'; Args = '-q' }
   )
   ```

4. Re-run `Install.ps1`. Installers not listed in config are only reported, never
   executed, so it is safe to stage files here first.
