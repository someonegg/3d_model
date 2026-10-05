# 星链伸缩杖 · FDM：设计与验证

本文件供源码维护使用，记录模型参数与设计约束；打印及装配步骤见同目录的 README.md。

## 核心参数

参数来源：`parameters.json`。

| 参数 | 数值 | 作用 |
| --- | --- | --- |
| `clearance_per_side_mm` | 0.30 mm / 侧 | 滑动间隙；增大更易滑动，也会增加晃动，调整后仍须保证固定端挡墙厚度。 |
| `detent_interference_mm` / `detent_depth_mm` | 0.70 / 1.10 mm | 卡位干涉控制解锁时的弹舌挠动，凹槽深度容纳凸起；干涉须比槽深小至少 0.15 mm。 |
| `detent_root_diameter_mm` | 3.6 mm | 圆顶定位凸点的根部直径；与连接片凹窝配合保持收拢。 |
| `anchor_wall_minimum_mm` / `anchor_neck_fillet_mm` | 2.40 / 0.80 mm | 固定端实心宽头的挡墙最低厚度及连接颈根部圆角半径，影响防脱与根部强度。 |
| `locator_clearance_mm` / `locator_vertical_clearance_mm` | 0.15 / 0.20 mm | 双侧粗榫的单侧横向及上下间隙，承担抗晃约束；卡位负责保持收拢。 |
| `locator_engagement_mm` / `locator_width_mm` | 3.8 / 3.2 mm | 粗榫插接深度与宽度，保留入口倒角及免支撑斜面，尖端最薄 2.4 mm。 |
| `base_height_mm` / `body_height_mm` / `slider_thickness_mm` | 7.6 / 10.0 / 3.4 mm | 底座高、壳体厚及连接片厚度参数（抬高连接颈厚度）；盖板主体厚 2.4 mm。 |
| `floor_mm` | 1.6 mm | 底板厚度；需保证连接片下方间隙及粗榫尖端至少 2.4 mm 厚度。 |
| `flag_thickness_mm` / 有效长度 | 1.6 / 10.4 mm | 弹舌厚度及根部至凸点的有效长度，影响解锁挠动。 |
| `pin_shaft_length_mm` | 9.8 mm | 柱径 2.96 mm，销头厚 1.2 mm，销总长 11.0 mm；13 根统一使用。 |

