# 开发指南

## 目录约定

```text
models/<模型 ID>/
  model.json           # 资源清单与构建输入
  README.md            # 下载、打印、装配及验收状态
  parameters.json      # 可选的模型参数
  src/                 # build.py、verify.py、slice.py 及专用几何代码
  references/          # 建模底图、参考照片、生成提示词
  *.stl / *.glb        # 发布产物；多零件可使用 parts/
  *.png / *.json       # 预览、装配数据和校验报告
```

只发现 `models/` 的直接子目录，忽略隐藏目录。模型 ID、变体 ID 和成品文件名保持稳定，网页地址为 `models/<ID>/<资源路径>`。发布的 `references.md` 是用户说明，留在模型顶层；`references/` 内的建模素材不发布。

模型 README 按用途组织下载与尺寸、打印、装配或换色、验收状态、维护入口。参数和操作步骤在每个模型中保留完整；公共工具说明只维护在本文。验收状态写实际结果，不添加泛化免责声明，切片耗时和诊断引用报告。

## 修改模型

```sh
npm run models:build -- coin-sacagawea
npm run models:validate -- --all
```

修改脚本后手动执行 `models:build`：工具依次生成产物、校验最终模型几何、执行模型专项验收、检查产物及输入并记录最终哈希，全部通过后才发布。正式模型声明 `inputs`；源码或素材改变后必须重新构建，单独校验不能确认旧产物对应新输入。模型产物和校验报告均提交 Git，其中 STL 由 Git LFS 管理。目录切换、回滚和并发保护见后文“发布与临时目录”。

开发页面在模型资产变化后自动刷新并保留视角；报告过期时显示“待重新校验”。正式站点构建要求模型齐全且报告未过期。

打印模型检查退化面、闭合边、绕序和每个连通实体的正体积，允许多个独立实体，不自动修复。展示模型只要求可解析、资源齐全、非空且坐标有效。

## 添加模型

复制 [`tools/model.template.json`](../tools/model.template.json) 为 `models/<模型 ID>/model.json`，填写 ID（与目录名相同）、名称、简介和资源路径。模板包含 `build`、`verify` 和 `inputs` 示例；仅导入已有模型时删除这些字段，无专项脚本时删除 `verify` 及对应输入。导入模型在添加文件、预览图和 README 后执行校验；生成模型准备脚本后执行 `models:build`，即可在模型库中发现。

- `purpose`：`print` 或 `display`。打印校验只接受 STL；其他格式作为独立展示模型登记。
- `units`：STL 使用 `mm`、`cm` 或 `m`；GLB/glTF 使用 `m`。`up`：STL 使用 `Y` 或 `Z`；GLB/glTF 使用 `Y`。
- `variants`：每个变体包含稳定 `id`、显示名称 `name`、相对路径 `file`。
- `build`：可选 Python 脚本，必须是模型目录内的文件并声明在 `inputs` 中。必须读取 `MODEL_OUTPUT_DIR` 环境变量作为产物目录；未设置时写入模型顶层，不能写到 `src/`。脚本使用 `main()` 入口，导入时不生成产物或执行验收；参考素材从模型的 `references/` 读取。
- `verify`：可选 Python 专项验收脚本，需同时声明 `build`，并将脚本及依赖加入 `inputs`。通用几何校验通过后执行；从 `MODEL_OUTPUT_DIR` 读取本次产物，工作目录为模型顶层（`model.json` 所在目录）。允许生成声明在 `artifacts` 中的报告，不得修改已经校验的模型及其依赖；失败以非零退出码终止，旧产物不发布替换。未声明时跳过。独立 `models:validate` 同样执行通用校验及已声明的专项验收，不调用构建脚本。
- `inputs`：构建输入文件列表，路径相对模型目录；共享源码可使用 `../../tools/...`，但不得越出模型库根目录。输入哈希只用于构建追溯，不发布输入文件。新增建模依赖时同步此列表。
- `preview`、`readme`：预览图和说明文件的相对路径。
- `artifacts`：可选的附加产物相对路径列表，例如局部预览或细节检查报告。统一构建检查文件完整性，校验报告记录其哈希。

所有发布资源必须位于该模型目录内。开发服务和静态站点只提供声明的资源及 glTF 依赖，不发布建模脚本或参考素材。glTF 支持本地纹理、缓冲文件和内嵌 data URI；不支持远程依赖、Draco/Meshopt/KTX2 压缩或动画播放，只展示默认场景静态姿态。

### 跨模型资源与切片

`models:build -- --all` 按 `inputs` 中的跨模型引用排序，上游先构建；循环依赖会报错。单独重建不会自动重建其他模型。Volvo 展示模型依赖打印模型的产物和有效校验报告，应先重建 `volvo-xc60-2022`，再重建 `volvo-xc60-2022-display`。

键盘解压器和 Volvo 的可选切片入口为 `models/<ID>/src/slice.py`。脚本默认使用本机 macOS Bambu Studio，通过 `--studio`、`--profiles` 指定其他安装路径；`--output-dir` 指定切片工作区。公共配置继承、哈希、进程调用和运行元数据读取位于 `tools/slicing.py`，模型参数及专项检查留在各自脚本中。

构建会重置切片报告为 `not-run`。切片完成后运行 `models:validate` 刷新报告；软件版本和诊断取自运行日志或本次调用的应用元数据，无法识别版本时记录未知。键盘脚本的 `--collect-only` 复核已有 3MF 的几何，版本仅取原日志，不使用当前安装版本推断历史版本。切片工程与 G-code 留在 `tmp/`，不作为站点资源发布。

## 静态站点

```sh
npm run build
npm run preview
```

`build` 检查校验报告，在 `tmp/site/` 组装模型资源和前端产物，成功后整体发布为 `dist/`，不重新建模。上传 `dist/` 到 HTTP 静态服务即可部署，支持根路径或子目录。模型选择通过查询参数保存，无需路由回退；不支持直接通过 `file://` 打开。

构建暂存目录 `tmp/site/`、最终输出 `dist/`、虚拟环境与缓存不提交。

## 检查与测试

```sh
npm test
npm run check
npm run format:check
npx playwright install chromium # 首次运行浏览器测试前安装
npm run test:e2e
```

- `npm test`：运行 `tests/tooling/` 的流程测试和 `tests/models/` 的独立算法测试；不读取正式 STL 或成品报告。可用 `npm test -- -p test_bookmark.py` 按文件筛选。
- `npm run check`：检查网页源码、浏览器测试和 Playwright 配置的 TypeScript 类型。
- `npm run format:check`：检查格式；使用 `npm run format` 修正。范围不包含 Python 文件。
- `npm run test:e2e`：生成 `tmp/fixtures/` 测试资源并构建正式站点，启动静态预览（4273）和开发服务（5273）。端口被占用时直接失败。模型热更新测试使用独立工作区，结束后清理。

浏览器测试失败时保留自动截图和 trace，均位于 `tmp/test-results/browser/`。可用 `npx playwright show-trace <trace.zip 路径>` 排查。

浏览器测试由通用交互、全库资源与模型特有行为组成：全库统一检查说明图片、预览资源和移动端布局；模型专项案例只保留配合试片下载、装配状态切换及整套下载等行为。尺寸、网格完整性和工艺约束由模型校验负责，不在浏览器中重复检查。新增模型无需复制一套加载、说明和布局测试。

## 工具入口

`tools/models.py` 是 Python 命令入口，`tools/model_library/` 负责资源清单、几何校验和构建发布；`tools/runtime.mjs` 解析仓库与 Python 路径，`tools/model-plugin.mjs` 提供 Vite 模型服务。

工具支持 `--model-root <目录>` 指定模型库根目录（其中包含 `models/`）；`site --output <目录>` 指定站点暂存目录，默认是源码仓库内的 `tmp/site/`。输出目录不得使用源码或模型目录；已有非空目录必须包含站点的 `catalog.json`，才允许替换。`publish` 默认将源码仓库的 `tmp/site/` 安全移动为同一仓库的 `dist/`，也可使用 `--staging` 和 `--output` 改写路径。Vite 开发服务通过 `MODEL_ROOT` 指定模型库，默认使用仓库根目录，同样要求其中包含 `models/`。

几何校验仅由用途、单位、坐标轴和模型文件集合决定；变体 ID、名称及简介变化不要求重新校验。Python 与 Vite 都只扫描库根目录的 `models/`，不需要维护仓库目录排除清单。

日常流程为修改源码、重建模型（含通用几何校验与专项验收）、运行受影响的流程或算法测试；影响网页时执行浏览器检查。

## 发布与临时目录

独立 `models:validate` 依次检查输入一致性、在临时目录的现有产物副本上执行通用几何校验与专项验收、复核模型及依赖和输入完整性，最后更新报告。专项脚本使用 `MODEL_OUTPUT_DIR` 读取副本，工作目录仍为模型顶层；可更新 `artifacts` 中声明的报告。全部通过且发布前确认原目录未变化后，使用目录切换及回滚机制发布报告，现有模型几何保持不变。校验或发布失败保留原报告；外部并发修改不会被覆盖。输入变化时仍须先重建，不能通过独立校验刷新输入哈希。开发热更新和静态站点构建不自动执行完整验收。

模型构建、校验和站点发布先在临时目录准备完整内容，再整体切换目标目录；复制或切换失败时回滚到上次成功内容。这不是断电或强制终止下的持久化事务，切换期间可能有短暂的目录不可见窗口。若回滚也因文件系统异常失败，工具会保留并输出工作区中的 `backup/` 路径，恢复文件系统后可手动移回。

构建、校验和发布使用的内部事务目录位于源码仓库的 `tmp/`，不受当前工作目录或 `--model-root` 影响；这些带随机后缀的目录通常会在完成或失败回滚后自动清理。模型及站点的发布目标必须与源码仓库 `tmp/` 位于同一文件系统，否则会在移动原目录前报错。默认路径用途如下：

- `tmp/site/`：站点暂存内容，成功发布后移动为源码仓库的 `dist/`。
- `tmp/tests/`：Python 测试工作区，测试结束后自动清理。
- `tmp/fixtures/`：浏览器测试素材。
- `tmp/test-results/browser/`：浏览器截图、trace 和运行结果。
- `tmp/playwright-report/`：手动启用的 HTML 报告；默认不启用。

依赖环境和工具缓存保持原位。
