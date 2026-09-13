# 模型工作台

保存模型源码、预览和 3D 打印文件。网页支持浏览 STL、GLB/glTF、切换视角与变体，以及下载模型。

## 开始使用

需要 Node.js 22.12+、Python 3.12 和 Git LFS。

```sh
git lfs install
git lfs pull
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci
npm run dev
```

打开终端显示的地址。Windows 安装依赖使用 `.venv\Scripts\python -m pip install -r requirements.txt`。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `npm run models:build -- <模型 ID>` | 重建指定模型并完成几何及专项验收；`--all` 处理全部模型 |
| `npm run models:validate -- --all` | 对现有模型文件执行通用几何校验及已声明的专项验收 |
| `npm run build` | 生成静态站点 `dist/` |
| `npm test` | 运行流程与独立算法测试 |
| `npm run test:e2e` | 构建站点并运行浏览器测试；首次先执行 `npx playwright install chromium` |

模型源码、模型产物和校验报告均提交 Git，STL 产物由 Git LFS 管理。修改模型后先重建，再构建静态站点。

模型接入、校验规则、部署及测试说明见 [开发指南](docs/development.md)。打印尺寸与工艺参数见 `models/<模型 ID>/README.md`。

模型按目录集中在 `models/`：`src/` 保存脚本，`references/` 保存参考素材，模型顶层保存参数、用户说明和发布产物。公共构建与校验工具位于 `tools/`。

## 协作规范

- Git 提交消息使用英文。
- 从生成源码修改模型并重建，同步受影响的变体、预览、报告、说明和测试；局部修改需核对范围外曲面及未修改版本保持一致。
- 校验最终导出文件，按改动运行相关回归；影响网页展示、资源或下载时执行浏览器检查。按实际完成的检查报告结果。
- 按实际尺寸、喷嘴和层高检查细节；FDM 浅浮雕流程见 [fdm-relief](.agents/skills/fdm-relief/SKILL.md)。
- 清理本次无用临时产物前检查引用；保留并说明必要基线，不删除用户原有文件或依赖环境。
- 工艺版本命名为“模型名 · 工艺”，尺寸放在参数和说明中。
