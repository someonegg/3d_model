# 江南石桥书签 · FDM

原创江南石桥、柳树、流水倒影与远山，以黑色底层和不同厚度的白色覆盖层表现灰度。采用类似 HueForge 的耗材绘画原理，由脚本生成，不是 HueForge 项目文件。

## 下载与尺寸

- `bookmark-jiangnan-bridge-fdm.stl`：45 × 150 mm，厚 0.52～1.32 mm，圆角半径 3 mm，平背单面，无穿绳孔。
- `preview.png`：未校准的正式灰度预览。
- `validation.json`：最终 STL 的通用几何校验结果。

## 打印与换色

STL 默认使用 P2S、0.4 mm 喷嘴，导入单位选择 mm，保持 100% 比例、平背朝下。STL 不包含颜色或暂停信息。

使用黑白 PLA，首层 **0.2 mm**，其余层高 **0.08 mm**，填充 **100%**；关闭可变层高、支撑和熨烫，不缩放 Z。温度按实际耗材和打印板配置。

切片应为 **15 层**：前 5 层黑色，至 0.52 mm；**第 6 层开始换白色**，该层顶面为 **0.60 mm**。使用 AMS 时，将前 5 层设为黑料、第 6 层起设为白料，并映射到实际料槽。无 AMS 时，在第 6 层开始前设置暂停，换白料并排净黑料。打印前核对首层高度、层数与颜色分界，冷却后取件，避免弯折薄处。

## 验收状态

通用几何校验通过；实物试打未记录。

## 灰度校准与维护

仓库中的 `references/source.png` 是生成高度层级的源图，`parameters.json` 控制 0～10 层白色覆盖的灰度映射；两者均为建模输入，不随站点发布。

`parameters.json` 的 `tone_values` 默认为 0～255 线性分布，未模拟实际耗材透光效果。校准时，在固定光照和曝光下测量 0～10 层白色覆盖的相对灰度，填入 11 个严格递增值。若相邻厚度无法区分，可更换白料或调整覆盖厚度。

从仓库根目录运行：

```sh
npm run models:build -- bookmark-jiangnan-bridge-fdm
npm run build
```

源图与提示词见 `references/source.png`、`references/source-prompt.md`，共享书签几何与灰度映射位于 `tools/bookmark_relief.py`。脚本支持 `MODEL_OUTPUT_DIR`，无需 HueForge；构建生成 `bookmark-jiangnan-bridge-fdm.stl` 和正式 `preview.png`，随后对最终 STL 执行通用几何校验。尺寸和层高受脚本约束，修改时需同步调整说明。
