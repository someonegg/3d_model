# Volvo XC60 2022 智远豪华版 · FDM：设计与验证

本文件供源码维护使用，记录模型参数与设计约束；打印及装配步骤见同目录的 README.md。

## 核心参数

参数来源：`parameters.json`。

| 参数 | 数值 | 作用 |
| --- | --- | --- |
| `scale` / `shell_mm` | 24 / 1.60 mm | 1:24 比例及车壳壁厚；壁厚按打印要求设置。 |
| `door_gap_mm` | 0.35 mm / 侧 | 前门与车壳的避让间隙。 |
| `hinge_pin_mm` / `hinge_bore_mm` | 1.50 / 1.85 mm | 门销与孔直径，直径差 0.35 mm；每端轴向余量为 `hinge_axial_gap_mm` 0.25 mm。 |
| `axle_mm` / `axle_bore_mm` | 2.00 / 2.40 mm | 轮轴与底盘孔直径，直径差 0.40 mm，供车轴滚动。 |
| `door_open_deg` | 60° | 前门最大开角，由几何止挡限制。 |

