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
| `marker` | 定位标记 `[x, y, z]`，三个有限数值，使用场景坐标（米、Y 向上） |
| `targets` | 必填且非空的高亮目标名称数组，可指定零件或组件节点 |
| `transparentTargets` | 必填的透明目标名称数组；无需透明时传 `[]` |
| `opacity` | 可选透明度，有限数值，范围大于 0 且不大于 1，默认 `0.2` |
| `markerRadius` | 可选标记半径，有限正数，单位米，默认 `0.0012` |

目标名称必须位于 `assembly-root` 内。组件目标会作用于其后代网格。参数检查以 [装配播放器](../viewer/src/assembly.ts) 为准。

## 网页入口与验证

模型页支持 `index.html?model=<ID>&mode=assembly` 直达。模型 README 中使用 `../../index.html?model=<ID>&mode=assembly`，相对发布后的模型目录解析。离线下载包中的该网页入口需要站点环境；离线查看使用 `assembly.glb`，须由支持 glTF 动画的软件打开。

浏览器支持播放、暂停、前后步骤和旋转视角；切换到后台时暂停，返回后续播。

动画应与最终导出的零件对应，并检查定位、运动轴线、安装路径和结束姿态。动画演示顺序与运动，不模拟胶合、弹性受力或实际配合手感。修改动画后运行模型专项验收及相关浏览器测试。
