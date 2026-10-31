"""Microsoft Store package (MSIX) from the PyInstaller program folder. The Store signs the package itself, so no
code-signing certificate is needed for this route; a package built here is for upload to Partner Center (and for a
local test after signing it with a test certificate).

  python tools/make_msix.py --app build/dist/NovaSolverStudio --version 0.7.0 \
      --identity <Package/Identity/Name> --publisher "CN=..." --publisher-name "NovaSolver"

identity and publisher are the values Partner Center shows under Product identity once the app name is reserved.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
         xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
         xmlns:desktop6="http://schemas.microsoft.com/appx/manifest/desktop/windows10/6"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap uap3 desktop desktop6 rescap">
  <Identity Name="{identity}" Publisher="{publisher}" Version="{version}.0" ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>NovaSolver Studio</DisplayName>
    <PublisherDisplayName>{publisher_name}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
    <!-- Cases, solver downloads and the window profile are shared with the MCP server and the solver processes, so
         writes to AppData must not be redirected into the package's private copy. -->
    <desktop6:FileSystemWriteVirtualization>disabled</desktop6:FileSystemWriteVirtualization>
    <desktop6:RegistryWriteVirtualization>disabled</desktop6:RegistryWriteVirtualization>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0"/>
  </Dependencies>
  <Resources>
    <Resource Language="ja-JP"/>
    <Resource Language="en-US"/>
    <Resource Language="zh-CN"/>
  </Resources>
  <Applications>
    <Application Id="NovaSolverStudio" Executable="NovaSolverStudio.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="NovaSolver Studio" Description="Structural, thermal and flow simulation on your own computer"
                          BackgroundColor="transparent" Square150x150Logo="Assets\\Square150x150Logo.png"
                          Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png"/>
      </uap:VisualElements>
      <Extensions>
        <uap:Extension Category="windows.fileTypeAssociation">
          <uap:FileTypeAssociation Name="nscase">
            <uap:DisplayName>NovaSolver Studio case</uap:DisplayName>
            <uap:SupportedFileTypes><uap:FileType>.nscase</uap:FileType></uap:SupportedFileTypes>
          </uap:FileTypeAssociation>
        </uap:Extension>
        <!-- "NovaSolverStudio.exe mcp" for Claude and other MCP clients, from any folder -->
        <uap3:Extension Category="windows.appExecutionAlias" Executable="NovaSolverStudio.exe" EntryPoint="Windows.FullTrustApplication">
          <uap3:AppExecutionAlias><desktop:ExecutionAlias Alias="NovaSolverStudio.exe"/></uap3:AppExecutionAlias>
        </uap3:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust"/>
    <rescap:Capability Name="unvirtualizedResources"/>
  </Capabilities>
</Package>
"""


def makeappx() -> str:
    found = shutil.which("makeappx.exe")
    if found:
        return found
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    cands = sorted(kits.glob(r"10.*\x64\makeappx.exe"), reverse=True) + list(kits.glob(r"x64\makeappx.exe")) \
        if kits.is_dir() else []
    if not cands:
        sys.exit("makeappx.exe not found (Windows SDK). GitHub's windows runners have it.")
    return str(cands[0])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True, type=Path)
    ap.add_argument("--version", required=True)
    ap.add_argument("--identity", required=True)
    ap.add_argument("--publisher", required=True)
    ap.add_argument("--publisher-name", default="NovaSolver")
    ap.add_argument("--out", type=Path, default=ROOT / "release")
    a = ap.parse_args()
    if not (a.app / "NovaSolverStudio.exe").is_file():
        sys.exit(f"no NovaSolverStudio.exe in {a.app}")
    stage = ROOT / "build" / "msix"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(a.app, stage)
    shutil.copytree(ROOT / "assets" / "msix", stage / "Assets")
    (stage / "AppxManifest.xml").write_text(MANIFEST.format(
        identity=escape(a.identity), publisher=escape(a.publisher, {'"': "&quot;"}),
        publisher_name=escape(a.publisher_name), version=a.version), encoding="utf-8")
    a.out.mkdir(parents=True, exist_ok=True)
    out = a.out / f"NovaSolverStudio-{a.version}-win64.msix"
    subprocess.run([makeappx(), "pack", "/o", "/d", str(stage), "/p", str(out)], check=True)
    print(out, out.stat().st_size)


if __name__ == "__main__":
    main()
