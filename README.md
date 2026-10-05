# 模型工作台

保存模型源码，构建预览和 3D 打印文件。网页支持浏览 STL、GLB/glTF、切换视角与变体，以及下载模型。

## 模型目录

各模型说明包含文件选择、实际尺寸、打印设置及验证状态。装配模型另有零件清单与装配步骤；展示用 GLB 不用于打印。

| 类别 | 模型说明 | 特点 |
| --- | --- | --- |
| 耗材叠层书签 | [江南石桥书签 · FDM](models/bookmark-jiangnan-bridge-fdm/README.md) | 45 × 150 mm，黑白山水 |
| 耗材叠层书签 | [牡丹鹦鹉书签 · FDM](models/bookmark-lovebird-fdm/README.md) | 45 × 150 mm，照片转绘 |
| 耗材叠层书签 | [珠海渔女书签 · FDM](models/bookmark-zhuhai-fisher-girl-fdm/README.md) | 45 × 150 mm，海景浮雕 |
| 硬币浮雕 | [萨卡加维亚硬币](models/coin-sacagawea/README.md) | 直径 60 mm，半片与完整双面版本 |
| 硬币浮雕 | [萨卡加维亚硬币 · FDM](models/coin-sacagawea-fdm/README.md) | 直径 60 mm，为 0.4 mm 喷嘴简化细节 |
| 解压器 | [解压按键 · FDM](models/fidget-button-fdm/README.md) | 四件装配，可更换弹片 |
| 解压器 | [键盘解压按键器 · FDM](models/keyboard-fidget-fdm/README.md) | 六件装配，带段落弹舌与装配动画 |
| 变形玩具 | [伸缩手里剑玩具 · FDM](models/retractable-shuriken-fdm/README.md) | 七件装配，四翼联动与装配动画 |
| 变形玩具 | [星链伸缩杖 · FDM](models/star-chain-fdm/README.md) | 31 件装配，六节伸缩链条 |
| 车模 | [Volvo XC60 2022 智远豪华版 · FDM](models/volvo-xc60-2022/README.md) | 1:24，52 个打印零件，需另备五金 |

模型说明中的下载链接相对生成目录，构建后在网页中使用。几何校验和切片检查不能代替实物试打，各模型的验证状态见说明末尾。

## 开始使用

需要 Node.js 22.12+、Python 3.12 和 Git。

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci
npm run dev
```

开发命令会先增量构建模型，再启动服务；打开终端显示的地址。Windows 安装依赖使用 `.venv\Scripts\python -m pip install -r requirements.txt`。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `npm run build` | 按依赖顺序增量构建模型并发布站点；`-- --force` 强制重建全部模型 |
| `npm run dev` | 增量构建模型后启动开发服务，可透传 Vite 参数 |
| `npm run preview` | 预览已经构建的站点 |
| `npm test` | 运行流程与独立算法测试 |
| `npm run test:e2e` | 构建站点并运行浏览器测试；首次先执行 `npx playwright install chromium` |

模型文件只提交源码及导入源模型；生成模型、预览、下载包和校验报告位于 `build/models/`，不提交。修改模型后运行 `npm run build`。

模型接入、目录约定、增量构建、下载包、部署和测试见 [开发指南](docs/development.md)，装配动画数据约定见 [装配动画参考](docs/assembly.md)。

## 协作规范

- 工艺版本命名为“模型名 · 工艺”，尺寸放在参数和说明中。
- 从生成源码修改模型并重建，同步受影响的变体、预览、报告、说明和测试；局部修改需核对范围外曲面及未修改版本保持一致。
- FDM 功能结构优先采用粗壮、简洁的承靠与连接方式，关键定位、锁定和承力不应依赖细小卡齿、薄弹片或极小配合间隙；FDM 浅浮雕流程见 [fdm-relief](.agents/skills/fdm-relief/SKILL.md)。
