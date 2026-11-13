# NovaSolver Studio 0.8.0

## English
- **NovaSolver Genesis** (new): topology optimisation on your part. With its supports and loads, Genesis seeks a
  higher-stiffness shape for the volume you choose; for heat, a lower-temperature layout for its sources and sinks. 3D-print overhang,
  extrusion and symmetry constraints, an optional finishing pass on a finer grid near the surface. The result is a
  closed STL (also smoothed), and an extruded part is written as a flat-faced STEP. Example: a cantilever on 40,000
  cells at 30 % volume keeps 62 % of the full part's stiffness.
- Genesis refuses what it cannot handle yet (contact pairs, thermal loads on a structure) instead of leaving them out,
  and warns when the load or heat no longer reaches the supports; its stiffness figures are then not shown.
- FreeCAD workbench: send the part to Studio as STEP and bring the Genesis result back into the same document.
- MCP: `run_genesis` and `genesis_result` (37 tools). Codex setup now pins the matching Studio package.
- Reimport exported STL/STEP and analyse it with the intended supports and loads. Voxel estimates and smoothed geometry are not interchangeable; smoothing needs its own check.

## 日本語
- **NovaSolver Genesis**（新機能）：部品そのものでトポロジー最適化をします。付けた固定と荷重のもとで、決めた体積で剛性を高める形を
  探索します（熱では、発熱と放熱先の条件に応じて温度を下げる形）。3D プリントの張り出し・押し出し・対称面を指定でき、表面の近くだけを細かい
  格子で作り直す「仕上げ」も選べます。結果は閉じた STL（滑らかにした版も）で保存でき、押し出しを指定した形は平らな面の STEP で
  も出せます。例：片持ち梁を 4 万セル・体積 30 % で求めた形は、元の部品の剛性の 62 % を保ちます。
- 接触ペアや構造の熱荷重など、Genesis がまだ扱えない条件は、黙って外さずに実行前に断ります。荷重や熱が支持部まで届かない
  形になったときは警告し、剛性の数字は出しません。
- FreeCAD ワークベンチ：部品を STEP のまま Studio へ送り、Genesis の結果を同じドキュメントへ取り込めます。
- MCP：`run_genesis` と `genesis_result` を追加（全 37 ツール）。Codex連携はStudioと同じ版のパッケージを指定します。
- 書き出したSTL／STEPを再読込し、実際の固定・荷重で解析してください。ボクセルの推定値は書き出した形状の検証値ではなく、平滑化した形状も別途確認が必要です。

## 中文
- **NovaSolver Genesis**（新功能）：直接在零件上进行拓扑优化。在设定的约束和载荷下，寻找给定体积下刚度更高的形状（热问题中，
  根据热源和散热处寻找温度更低的布局）。可指定 3D 打印悬垂、拉伸和对称面，并可选择只在表面附近用更细网格重新优化的"精修"。
  结果保存为封闭的 STL（也有平滑版），指定拉伸的形状还可输出为平面构成的 STEP。示例：悬臂梁在 4 万个单元、30 % 体积下求得的
  形状保留了原零件 62 % 的刚度。
- 对于 Genesis 暂不支持的条件（接触对、结构上的热载荷），在运行前明确拒绝，而不是悄悄忽略；当载荷或热量不再传到支撑处时给出
  警告，并且不显示刚度数值。
- FreeCAD 工作台：把零件以 STEP 发送到 Studio，并把 Genesis 结果导入同一文档。
- MCP：新增 `run_genesis` 和 `genesis_result`（共 37 个工具）。Codex配置使用相同版本的Studio软件包。
- 请重新导入导出的STL／STEP，并按实际约束和载荷进行分析。体素估算不能替代导出形状的验证，平滑后的形状也需要单独检查。
