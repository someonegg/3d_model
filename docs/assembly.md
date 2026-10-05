# 装配动画参考

本页面向模型开发者。模型接入和资源发布见 [开发指南](development.md)；打印与装配步骤保留在各模型 README 中。

## 接入与生成

在 `model.json` 中设置 `"assembly": "assembly.glb"`，并将该文件同时列入 `artifacts` 和 `publish`。下载包需要包含动画时，也在 `bundle.json` 中声明。

使用 [AssemblyWriter](../tools/assembly_gltf.py) 写入网格、材质和关键帧；消费该工具的模型须在 `inputs` 中声明 `../../tools/assembly_gltf.py`。场景采用米单位、Y 向上，所有零件位于具名根节点 `assembly-root` 内，具名节点不得重名。一个动画片段控制零件运动，时长须与步骤数据的 `duration` 一致（误差不大于 0.00001 秒）。

## 场景与步骤数据

glTF 场景的 `extras.assembly` 保存以下字段，加载后对应 `scene.userData.assembly`。

| 字段 | 约定 |
| --- | --- |
| `version` | 固定为 `1` |
| `duration` | 总时长，有限正数，单位秒 |
| `steps` | 非空步骤数组，按时间顺序排列 |

每个步骤的数据约定如下。

| 字段 | 约定 |
| --- | --- |
| `title` / `hint` | 步骤标题与安装提示，字符串 |
| `start` / `end` | 开始和到位时间，单位秒；满足 `0 ≤ start < end ≤ duration`；第一步从 0 开始，后一步的 `start` 必须大于前一步的 `end` |
| `marker` | 定位标记 `[x, y, z]`，三个有限数值，使用 `assembly-root` 的局部坐标（米；根节点无旋转时为 Y 向上） |
| `targets` | 必填且非空的高亮目标名称数组，可指定零件或组件节点 |
| `transparentTargets` | 必填的透明目标名称数组；无需透明时传 `[]` |
| `opacity` | 可选透明度，有限数值，范围大于 0 且不大于 1，默认 `0.2` |
| `markerRadius` | 可选标记半径，有限正数，单位米，默认 `0.0012` |

目标名称必须位于 `assembly-root` 内。组件目标会作用于其后代网格。`marker` 不跟随目标节点运动；根节点发生变换时，标记随根节点一起变换。参数检查以 [装配播放器](../viewer/src/assembly.ts) 为准。

## 生成与验证要点

- 源模型为毫米、Z 向上时，网格、节点位移及标记统一转换；可参考 [键盘按键动画生成器](../models/keyboard-fidget-fdm/src/assembly.py)。旋转关键帧使用 glTF 四元数 `[x, y, z, w]`。
- `AssemblyWriter` 提供网格、关键帧与 GLB 写出功能，节点层级由模型脚本建立；它不负责步骤数据或装配正确性验收。
- 关键帧应覆盖最终时长。步骤之间的间隔可用于到位停留，最后一步允许早于 `duration` 结束；播放器在下一步开始前继续显示上一步提示。
- 专项验收应比较动画网格与最终打印零件，检查安装路径、运动轴线和结束姿态。网页加载成功仅说明资源可读且步骤协议有效。

## 网页入口与浏览器检查

模型页支持 `index.html?model=<ID>&mode=assembly` 直达。模型 README 中使用 `../../index.html?model=<ID>&mode=assembly`，相对发布后的模型目录解析。离线下载包中的该网页入口需要站点环境；离线查看使用 `assembly.glb`，须由支持 glTF 动画的软件打开。

浏览器支持播放、暂停、前后步骤和旋转视角；切换到后台时暂停，返回后续播。

动画演示顺序与运动，不模拟胶合、弹性受力或实际配合手感。修改后先构建模型并检查专项报告，再执行相关浏览器测试；完整检查使用 `npm run test:e2e`。已有测试夹具和构建站点时，可执行单项检查，例如：

```sh
npx playwright test tests/browser/keyboard.spec.ts
```

浏览器检查应覆盖模式切换、播放与暂停、步骤跳转、结束状态和后台恢复；修改通用播放器时，还需覆盖其它已接入动画的模型。
