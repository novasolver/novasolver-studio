# NovaSolver Studio 验证手册 — 0.7.0

本文档记录 Studio 0.7.0 求解已知答案问题的准确程度。所有问题都可以用 `validation/suite.py` 重新计算。数值是 2026-10-31 在下列环境中求解的结果，没有手工抄写。

环境: Windows-10-10.0.19045-SP0, Python 3.12.3, 8 CPU

## 汇总

43 个问题中 43 个在容差范围内（不合格 0，错误 0，无参考值 0）。

“网格收敛”表示 Studio 自身确认了在粗、标准、细三级网格下答案不变（GCI）。“单一网格”表示由于内存或时间原因只求解了一级。

## 结构

| 问题 | 检验内容 | 量 | Studio | 参考值 | 误差 | 容差 | 结果 | 网格 |
|---|---|---|---|---|---|---|---|---|
| 悬臂梁 | 一端固定的方形杆，在自由端施加载荷，求挠度和应力，并自动与梁理论的手算结果比较。 | Tip deflection (beam theory with shear correction) | 0.9762 mm | 0.9831 mm | -0.70 % | ±3 % | 合格 | 已收敛 |
| 带孔板拉伸 | 拉伸中心带孔的板，将孔边的应力集中系数与 Heywood 公式比较。 | Stress concentration Kt (Heywood) | 2.541 - | 2.512 - | +1.16 % | ±5 % | 合格 | 已收敛 |
| 悬臂梁固有频率 | 将钢梁模态与欧拉–伯努利梁理论解析解比较。 | Steel beam modes compared with the Euler–Bernoulli beam solution. | 206.5 Hz | 206.4 Hz | +0.04 % | ±2 % | 合格 | 已收敛 |
| 柱的屈曲（一端固定、一端自由） | 在细长方柱顶端施加压缩载荷，并将临界载荷与欧拉公式比较。 | Euler critical load, fixed-free column. | 2638 N | 2634 N | +0.12 % | ±2 % | 合格 | 已收敛 |
| 柱的屈曲（两端固定） | 两端固定的方柱沿轴向压缩，并将临界载荷与欧拉公式比较。 | Euler critical load, column clamped at both ends. | 4.196e+04 N | 4.215e+04 N | -0.46 % | ±2 % | 合格 | 已收敛 |
| 杆的疲劳（古德曼） | 以 0 ↔ 15 kN 反复拉伸杆件，并将疲劳安全系数与古德曼公式比较。 | Goodman diagram n = 1/(σa/Se + σm/Su). | 1.778 - | 1.778 - | -0.00 % | ±1 % | 合格 | 已收敛 |
| 两端约束杆热应力 | 两端仅约束轴向位移，将热应力与EαΔT比较。 | Axial restraint at both ends; compare thermal stress with EαΔT. | 246 MPa | 246 MPa | +0.00 % | ±2 % | 合格 | 已收敛 |
| 杆的自由热膨胀 | 允许横向膨胀，将伸长量与αΔTL比较。 | Allow lateral expansion and compare elongation with αΔTL. | 0.12 mm | 0.12 mm | -0.00 % | ±1 % | 合格 | 已收敛 |
| 自重作用下的悬挂杆 | 用一维解析解验证自重引起的应力和位移。 | Verify self-weight stress and displacement against the one-dimensional solution. | 1.878e-04 mm | 1.878e-04 mm | -0.00 % | ±2 % | 合格 | 已收敛 |
| 旋转圆盘 | 采用四分之一圆盘及半厚度模型，将中心应力与平面应力解析解比较。 | Quarter disk with half thickness; compare centre stress with the plane-stress solution. | 35.54 MPa | 35.51 MPa | +0.07 % | ±2 % | 合格 | 已收敛 |
| 圆轴扭转 | 验证钢圆轴在扭矩作用下的剪应力和扭转角。 | Verify shear stress and twist of a steel shaft under torque. | 0.01615 rad | 0.01615 rad | +0.00 % | ±2 % | 合格 | 未确认收敛 |
| 大变形悬臂梁 | 不可伸长 Euler 弹性线，PL²/EI = 1，与线性解比较。 梁端约束允许横向应变。 | Inextensible Euler elastica, PL²/EI = 1; compare with the linear answer. The beam clamp permits lateral strain. | 60.22 mm | 60.34 mm | -0.20 % | ±2 % | 合格 | 已收敛 |
| 弹塑性杆 | 单轴双线性硬化：加载至 1%，卸载经过零力点，再回到零位移。 | Uniaxial bilinear hardening: load to 1%, unload through zero force, then return to zero displacement. | 268 MPa | 268 MPa | -0.00 % | ±1 % | 合格 | 已收敛 |
| 梁的塑性极限 | 理想塑性矩形悬臂梁，忽略剪切，P = σy b h²/(4L)。达到极限后以未收敛结束。 梁端约束允许横向应变。 | Perfectly plastic rectangular cantilever; P = σy b h²/(4L), neglecting shear. A limit run ends without convergence. The beam clamp permits lateral strain. | 1280 N | 1250 N | +2.44 % | ±3 % | 合格 | 单一网格 |
| 橡胶拉伸 | 可压缩 neo-Hookean 材料的均匀拉伸，λ = 2，侧向应力为零。 | Homogeneous compressible neo-Hookean tension, λ = 2 and zero lateral stress. | 29.54 MPa | 29.54 MPa | +0.00 % | ±2 % | 合格 | 已收敛 |
| 过盈配合 | Lamé 厚壁圆筒，平面应力。验证接触压力及环的环向应力。 | Lamé thick cylinders, plane stress. Contact pressure and ring hoop stress. | 76.92 MPa | 76.88 MPa | +0.06 % | ±2 % | 合格 | 已收敛 |
| 叠放方块 | 两个相接立方体的均匀压缩，验证无摩擦接触。 | Uniform compression of two touching cubes; frictionless contact. | 4000 N | 4000 N | -0.00 % | ±0.5 % | 合格 | 已收敛 |
| 摩擦方块 | 法向压力及剪切下的 Coulomb 粘着与滑动，软弹簧保证稳定。 此验证模型的泊松比为 0。 | Coulomb stick/slip under normal pressure and shear, with a soft spring. This patch uses Poisson ratio 0. | 400 N | 400 N | -0.00 % | ±1 % | 合格 | 已收敛 |
| 有间隙的两个块（接触） | 将相距 0.05 mm 的两个块压在一起。上下网格不同，比较间隙闭合后的接触力与手算结果。 | Uniform compression of two blocks in series: F = E (d − g) A / (2h). | 1.025e+05 N | 1.025e+05 N | -0.00 % | ±0.5 % | 合格 | 已收敛 |
| 分别划分网格的零件的绑定 | 将不共享节点的两个块粘接（绑定）后拉伸，确认结果与一根杆相同。 | Uniform tension of one bar: F = E d A / (2h). | 1.025e+05 N | 1.025e+05 N | -0.00 % | ±0.5 % | 合格 | 已收敛 |
| 圆柱与平面接触（赫兹） | 将钢圆柱压在钢块上，并将最大接触压力和接触宽度与赫兹公式比较（平面应变、1/4 模型）。 | Hertz line contact p0 = √(P E*/(πR)) and the contact half-width a. | 1407 MPa | 1408 MPa | -0.09 % | ±5 % | 合格 | 已收敛 |
| NAFEMS LE1 椭圆膜 | 曲线边界、对称面、向外压力 | σyy at D | 92.8 MPa | 92.7 MPa | +0.11 % | ±2 % | 合格 | 已收敛 |
| NAFEMS LE10 厚板弯曲 | 三维弯曲、分量约束、对称面 | σyy at D | -5.364 MPa | -5.38 MPa | -0.29 % | ±2 % | 合格 | 单一网格 |
| 封闭厚壁圆筒内压（Lamé） | 曲面压力、二次单元贴合曲面、1/8 对称 | hoop stress, mid wall | 20 MPa | 19.99 MPa | +0.01 % | ±1 % | 合格 | 未确认收敛 |
|  |  | axial stress, mid wall | 9.756 MPa | 9.756 MPa | +0.00 % | ±1 % | 合格 |  |
| 曲梁（Winkler–Bach） | 弯曲与轴力组合、曲率导致应力偏移 | inner fibre | 90.6 MPa | 89.41 MPa | +1.33 % | ±2 % | 合格 | 已收敛 |
|  |  | outer fibre | -51.92 MPa | -52.2 MPa | -0.54 % | ±2 % | 合格 |  |
| 钢铝串联杆 | 分部件材料、分量约束、粘接界面 | tip displacement | 0.1934 mm | 0.1937 mm | -0.17 % | ±1 % | 合格 | 已收敛 |
| 厚壁球内压 | 三个对称面、曲面内压 | inner displacement | 0.00195 mm | 0.001951 mm | -0.07 % | ±1 % | 合格 | 已收敛 |
|  |  | hoop stress at the bore | 7.136 MPa | 7.143 MPa | -0.10 % | ±3 % | 合格 |  |

## 传热

| 问题 | 检验内容 | 量 | Studio | 参考值 | 误差 | 容差 | 结果 | 网格 |
|---|---|---|---|---|---|---|---|---|
| 导热块 | 两端温度固定的长方体中的热传导。自动与傅里叶定律（Q = kAΔT/L）比较。 | Heat flow through the block (Fourier's law) | 40 W | 40 W | +0.00 % | ±2 % | 合格 | 已收敛 |
| 散热翅片 | 根部受热、被周围空气冷却的翅片。将根部散出的热量与翅片理论解析解比较。 | Heat through the fin base (fin theory) | 5.064 W | 5.066 W | -0.05 % | ±2 % | 合格 | 已收敛 |
| NAFEMS T4 带对流的二维导热 | 定温与对流组合 | T at E | 18.25 °C | 18.3 °C | -0.28 % | ±1 % | 合格 | 已收敛 |
| ISO 10211 附录A 案例1 | 建筑热桥计算验证（容差 0.1 K） | largest deviation of 28 points (at x 1 m, y 7 m) | 9.657 °C | 9.658 °C | -0.000693 °C | ±0.1 °C | 合格 | 未确认收敛 |
| ISO 10211 附录A 案例2（四种材料热桥） | 多材料、薄铝型材、表面热阻 | T at A | 7.065 °C | 7.1 °C | -0.035 °C | ±0.1 °C | 合格 | 单一网格 |
|  |  | T at B | 0.7613 °C | 0.8 °C | -0.0387 °C | ±0.1 °C | 合格 |  |
|  |  | T at C | 7.898 °C | 7.9 °C | -0.00191 °C | ±0.1 °C | 合格 |  |
|  |  | T at D | 6.272 °C | 6.3 °C | -0.0279 °C | ±0.1 °C | 合格 |  |
|  |  | T at E | 0.8275 °C | 0.8 °C | +0.0275 °C | ±0.1 °C | 合格 |  |
|  |  | T at F | 16.41 °C | 16.4 °C | +0.00842 °C | ±0.1 °C | 合格 |  |
|  |  | T at G | 16.33 °C | 16.3 °C | +0.0343 °C | ±0.1 °C | 合格 |  |
|  |  | T at H | 16.77 °C | 16.8 °C | -0.0329 °C | ±0.1 °C | 合格 |  |
|  |  | T at I | 18.33 °C | 18.3 °C | +0.0336 °C | ±0.1 °C | 合格 |  |
|  |  | heat flow | 9.492 W/m | 9.5 W/m | -0.00779 W/m | ±0.1 W/m | 合格 |  |
| 三层墙 | 分部件导热系数、界面温度连续 | T, first interface | 19.85 °C | 19.85 °C | -1.82e-12 °C | ±0.05 °C | 合格 | 已收敛 |
|  |  | T, second interface | 0.7634 °C | 0.7634 °C | -4.39e-12 °C | ±0.05 °C | 合格 |  |
|  |  | heat flow | 0.1527 W | 0.1527 W | +0.00 % | ±1 % | 合格 |  |
| 圆管径向导热 | 曲面温度条件、对数分布 | T at r = 15 mm | 53.21 °C | 53.2 °C | +0.00481 °C | ±0.05 °C | 合格 | 已收敛 |
|  |  | heat flow | 1813 W | 1813 W | +0.00 % | ±1 % | 合格 |  |

## 电

| 问题 | 检验内容 | 量 | Studio | 参考值 | 误差 | 容差 | 结果 | 网格 |
|---|---|---|---|---|---|---|---|---|
| 平行板电容器 | 计算平板间的电势和电容，并与 C = εA/d 对比。 | Capacitance (parallel-plate solution) | 23.24 pF | 23.24 pF | -0.00 % | ±1 % | 合格 | 已收敛 |
| 同轴电缆 | 计算同轴导体间的电容和电场，并与圆柱解析解对比。 | Capacitance (coaxial solution) | 0.9326 pF | 0.9326 pF | +0.00 % | ±1 % | 合格 | 已收敛 |
| 母排焦耳热 | 计算铜棒中的电流和温升，并用电阻与热传导解析解验证。 | Temperature rise (bar with cooled ends) | 7.641 K | 7.641 K | -0.00 % | ±1 % | 合格 | 已收敛 |

## 流动

| 问题 | 检验内容 | 量 | Studio | 参考值 | 误差 | 容差 | 结果 | 网格 |
|---|---|---|---|---|---|---|---|---|
| 顶盖驱动方腔流 | 顶盖滑动的方形腔内流动。CFD 的经典算例，与 Ghia 等人的参考值（Re=100）比较。 | Mean error of centreline u (Ghia et al. 1982, Re = 100) | -0.2134 m/s | -0.2109 m/s | +0.15 % | ±3 % | 合格 | 已收敛 |
| 平行平板间流动 | 两块平板之间的层流。确认充分发展后的速度分布是否为抛物线（泊肃叶流动）。 | Outlet centre velocity (Poiseuille u_max = 1.5 U) | 0.01497 m/s | 0.015 m/s | -0.23 % | ±2 % | 合格 | 单一网格 |

## 流动

| 问题 | 检验内容 | 量 | Studio | 参考值 | 误差 | 容差 | 结果 | 网格 |
|---|---|---|---|---|---|---|---|---|
| 圆管层流（Hagen–Poiseuille） | 内部流动的壁面摩擦与压力梯度 | pressure gradient, developed flow | 5.115 Pa/m | 5.11 Pa/m | +0.10 % | ±2 % | 合格 | 已收敛 |
| 突扩管损失（Borda–Carnot） | 湍流、分离与再附着、壁面边界层网格 | loss coefficient K | 0.5592 - | 0.5625 - | -0.59 % | ±5 % | 合格 | 单一网格 |
| 湍流圆管摩擦（Blasius） | 湍流壁面摩擦（壁函数、边界层网格） | pressure gradient, developed flow | 5541 Pa/m | 5304 Pa/m | +4.48 % | ±10 % | 合格 | 单一网格 |

## 外部流动

| 问题 | 检验内容 | 量 | Studio | 参考值 | 误差 | 容差 | 结果 | 网格 |
|---|---|---|---|---|---|---|---|---|
| 圆球绕流（阻力） | 求均匀来流中圆球的阻力系数，并与 Schiller-Naumann 公式（Re=100）比较。绕流的标准算例。 | Drag coefficient (Schiller-Naumann) | 1.1 - | 1.092 - | +0.79 % | ±8 % | 合格 | 已收敛 |

## 已知的限制

- 湍流壁面摩擦（圆管摩擦系数）强烈依赖壁面附近的网格。使用前请先查看表中 Blasius 的结果。
- 固定面的角点或尖锐内角处的应力在理论上为无穷大（奇异点）。Studio 会给出警告，不用于比较。
- NAFEMS LE10 的细网格需要 16 GB 以上内存，因此采用标准网格的结果。
- 接触、屈曲和疲劳通过上表中的基本问题（串联块、赫兹接触、欧拉屈曲、古德曼）进行验证。显式碰撞和壳单元不在本版本的验证范围内。

## 出处

- **ISO 10211 附录A 案例1**: ISO 10211:2017 Annex A, case 1 (28 grid points; exact series solution)
- **ISO 10211 附录A 案例2（四种材料热桥）**: ISO 10211:2017 Annex A, case 2: nine temperatures (±0.1 K) and 9.5 W/m (±0.1 W/m)
- **NAFEMS LE1 椭圆膜**: NAFEMS, The Standard NAFEMS Benchmarks, TNSB Rev. 3 (1990), LE1: σyy at D = 92.7 MPa
- **NAFEMS LE10 厚板弯曲**: NAFEMS TNSB Rev. 3, LE10: σyy at D = −5.38 MPa
- **NAFEMS T4 带对流的二维导热**: NAFEMS TNSB Rev. 3, T4: T at E = 18.3 °C
- **三层墙**: Hand calculation: series thermal resistances
- **两端约束杆热应力**: Axial restraint at both ends; compare thermal stress with EαΔT.
- **分别划分网格的零件的绑定**: Uniform tension of one bar: F = E d A / (2h).
- **厚壁球内压**: Lamé solution for a thick sphere, Timoshenko & Goodier §141
- **叠放方块**: Uniform compression of two touching cubes; frictionless contact.
- **同轴电缆**: Capacitance (coaxial solution)
- **圆柱与平面接触（赫兹）**: Hertz line contact p0 = √(P E*/(πR)) and the contact half-width a.
- **圆球绕流（阻力）**: Drag coefficient (Schiller-Naumann)
- **圆管层流（Hagen–Poiseuille）**: Hagen–Poiseuille: dp/dx = 32 μ U / d²
- **圆管径向导热**: Hand calculation: Q = 2πkLΔT / ln(b/a)
- **圆轴扭转**: Verify shear stress and twist of a steel shaft under torque.
- **大变形悬臂梁**: Inextensible Euler elastica, PL²/EI = 1; compare with the linear answer. The beam clamp permits lateral strain.
- **导热块**: Heat flow through the block (Fourier's law)
- **封闭厚壁圆筒内压（Lamé）**: Lamé solution, e.g. Timoshenko & Goodier, Theory of Elasticity, §28
- **带孔板拉伸**: Stress concentration Kt (Heywood)
- **平行平板间流动**: Outlet centre velocity (Poiseuille u_max = 1.5 U)
- **平行板电容器**: Capacitance (parallel-plate solution)
- **弹塑性杆**: Uniaxial bilinear hardening: load to 1%, unload through zero force, then return to zero displacement.
- **悬臂梁**: Tip deflection (beam theory with shear correction)
- **悬臂梁固有频率**: Steel beam modes compared with the Euler–Bernoulli beam solution.
- **摩擦方块**: Coulomb stick/slip under normal pressure and shear, with a soft spring. This patch uses Poisson ratio 0.
- **散热翅片**: Heat through the fin base (fin theory)
- **旋转圆盘**: Quarter disk with half thickness; compare centre stress with the plane-stress solution.
- **曲梁（Winkler–Bach）**: Winkler–Bach curved-beam formula, e.g. Roark's Formulas for Stress and Strain, 8th ed., §9.1
- **有间隙的两个块（接触）**: Uniform compression of two blocks in series: F = E (d − g) A / (2h).
- **杆的疲劳（古德曼）**: Goodman diagram n = 1/(σa/Se + σm/Su).
- **杆的自由热膨胀**: Allow lateral expansion and compare elongation with αΔTL.
- **柱的屈曲（一端固定、一端自由）**: Euler critical load, fixed-free column.
- **柱的屈曲（两端固定）**: Euler critical load, column clamped at both ends.
- **梁的塑性极限**: Perfectly plastic rectangular cantilever; P = σy b h²/(4L), neglecting shear. A limit run ends without convergence. The beam clamp permits lateral strain.
- **橡胶拉伸**: Homogeneous compressible neo-Hookean tension, λ = 2 and zero lateral stress.
- **母排焦耳热**: Temperature rise (bar with cooled ends)
- **湍流圆管摩擦（Blasius）**: Blasius: f = 0.316 Re^−0.25 (Re 20,000), dp/dx = f/d · ρU²/2
- **突扩管损失（Borda–Carnot）**: Borda–Carnot: K = (1 − A1/A2)² = 0.5625; turbulent, Re 10,000, k-ω SST
- **自重作用下的悬挂杆**: Verify self-weight stress and displacement against the one-dimensional solution.
- **过盈配合**: Lamé thick cylinders, plane stress. Contact pressure and ring hoop stress.
- **钢铝串联杆**: Hand calculation: u = F/A (L1/E1 + L2/E2)
- **顶盖驱动方腔流**: Mean error of centreline u (Ghia et al. 1982, Re = 100)

## 重新计算的方法

使用 Windows zip 版或 `pip install novasolver-studio`，获取仓库后运行：

```
python validation/suite.py
python validation/report.py validation/results/<version>.json
```
