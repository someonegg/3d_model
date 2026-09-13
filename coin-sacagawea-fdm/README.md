# 萨卡加维亚硬币 · FDM

为 Bambu P2S、0.4 mm 喷嘴、0.12 mm 层高重新塑形的 60 mm 装饰性浮雕。两个平背半片分别打印；不提供整枚双面变体。

人物、背婴与鹰参考原币构图，头发、衣褶及羽毛合并为宽结构；文字由独立粗体路径绘制，不从照片明暗生成高度。保留主要铭文与 2000 年份，省略微小铸记和签名。这是艺术重塑，不是原币扫描。

## 打印

| 文件 | 最终尺寸（mm） |
| --- | --- |
| `coin-sacagawea-fdm-obverse.stl` | 60 × 60 × 3.5533 |
| `coin-sacagawea-fdm-reverse.stl` | 60 × 60 × 3.5471 |

STL 单位 mm，以 100% 比例导入。两个半片平背贴热床、浮雕朝上打印，无需支撑。建议在 Bambu Studio 中选择 P2S 0.4 mm、Generic PLA 和 Arachne 墙生成器；首层和后续层均设为 0.12 mm，使用 3 圈墙、20% 陀螺填充，并关闭熨烫及裙边。更换首层高度会改变细节所处的分层位置，应重新检查切片预览。

底厚 2.04 mm，背景位于 Z=2.16 mm；主体基础高于背景约 0.36 mm，最高点分别高于背景约 1.3933、1.3871 mm。铭文高于背景 0.72 mm，边圈最高 0.96 mm。粘合时从正面绕水平轴翻到背面应正向观看，即两片背靠背后图案顶部朝相反方向。先干摆核对再粘合；两片厚度相加约 7.1004 mm，胶层会增加总厚度。

## 重建

从仓库根目录运行：

```sh
npm run models:build -- coin-sacagawea-fdm
npm run build
```

`relief.py` 定义造型与文字高度场，`build.py` 生成两个 STL 和唯一的正式 `preview.png`；`validation.json` 记录最终 STL 的通用几何校验结果。

参考来源：[美国铸币局设计资料](https://www.usmint.gov/learn/coins-and-medals/circulating-coins/sacagawea-golden-dollar)、[2000-S 图案参考照片](https://www.usacoinbook.com/coins/3381/dollars/native-american-sacagawea/2000-S/)。
