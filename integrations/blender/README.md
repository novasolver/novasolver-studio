# NovaSolver Studio for Blender

Check whether a model will hold before you print or make it. The add-on sends the active object to
[NovaSolver Studio](https://novasolver.jp/studio/) (free, open source, runs on your computer) as a new analysis case.

ブレンダーで作った形を、そのまま NovaSolver Studio（無料・ローカル実行）で強度や熱の解析にかけるアドオンです。

## Install

1. Install NovaSolver Studio (installer or zip from the download page).
2. Blender 4.2 or later: Edit > Preferences > Get Extensions > Install from Disk, choose `novasolver_studio-<version>.zip`.
3. 3D View sidebar (N) > **NovaSolver** tab.

## Use

1. Select the object. Modifiers are applied; the object's world position and scale are used.
2. Units: Scene Properties > Units. For printing work in millimetres, set Unit Scale to 0.001.
3. Choose the analysis (strength or heat) and the material (PLA, PETG, ABS, TPU, metals).
4. **Analyze in NovaSolver Studio**. Studio starts if needed and opens the part as a new case. Pick the faces that
   are fixed and loaded, and run. An AI assistant connected to Studio (MCP) can also do these steps.

## Privacy

The add-on writes a temporary STL (in the system temp folder, `novasolver_blender`) and talks only to Studio on
`127.0.0.1`. Nothing is sent to the internet; Studio itself keeps models on this computer (see Studio's `docs/PRIVACY.md`).

## Build

```
blender --command extension build --source-dir integrations/blender/novasolver_studio --output-dir release
```

GPL-3.0-or-later, like Blender and Studio.
