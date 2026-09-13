# 牡丹鹦鹉书签 · FDM

依据照片转绘的牡丹鹦鹉，朝左侧首、栖于树枝，背景为淡树林、阔叶与蕨叶。底图通过 imagegen 生成，遮挡的足爪与尾部作艺术补全。

## 下载与尺寸

- [书签 STL](bookmark-lovebird-fdm.stl)：45 × 150 mm，厚 0.52～1.32 mm，圆角 3 mm，平背单面，无绳孔。
- [灰度预览](preview.png)、[表面预览](surface-preview.png)、[分层预览](layers-preview.png)。

## 打印与换色

- P2S、0.4 mm 喷嘴、黑白 PLA；平背朝下，100% 比例与填充。
- 首层 0.20 mm，其余 0.08 mm；关闭可变层高、支撑和熨烫。
- 共 15 层：前 5 层黑色至 0.52 mm，第 6 层开始换白色，该层顶面 0.60 mm；白料覆盖 0～10 层。
- AMS 从第 6 层起映射白料；无 AMS 在第 6 层前暂停换料并排净黑料。STL 不携带换色信息。
- 高度表示白料覆盖厚度。`parameters.json` 的 11 档灰度尚未做耗材透光校准，预览为灰度示意。

## 验收状态

通用几何及专项校验通过；实物试打未记录。专项检查尺寸、单体、平背、离散层高、源图方向及眼部截面，结果见 [专项报告](detail-validation.json)。

## 维护与重建

`references/source.png` 是建模底图，生成提示词保存在 `references/source-prompt.md`。`src/build.py` 处理构图与灰度映射，共享几何位于仓库的 `tools/bookmark_relief.py`；`src/verify.py` 校验成品并生成表面和分层预览。

```sh
npm run models:build -- bookmark-lovebird-fdm
npm run build
```
