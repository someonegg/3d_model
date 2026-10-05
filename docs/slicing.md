# 切片与验证

本页面向模型开发者，说明切片入口和报告复核。模型构建与资源发布见 [开发指南](development.md)，各模型的打印设置与使用步骤见对应 README。

## 执行切片

**BambuStudio 必须在沙盒外运行，包括 GUI、CLI 切片及通过脚本间接调用；首次调用就使用沙盒外执行方式，遵循环境审批规则。** 仅读取安装目录中的配置文件不属于运行 BambuStudio。

切片读取 `build/models/<ID>/`；执行前先构建，确保输入与源码一致。模型切片统一通过 shell 入口执行；沙盒外审批可使用持久前缀 `["tools/slice-model.sh"]`。入口支持的模型见下表，固定使用项目 `.venv` 和共享运行器，也可通过绝对路径从其它目录调用。查看清单、参数及执行切片：

```sh
tools/slice-model.sh --list
tools/slice-model.sh <ID> --log-file "tmp/slicing logs/<ID>.log"
```

`--log-file` 合并保存标准输出与错误输出、覆盖旧日志并创建父目录；相对路径以仓库根目录为基准。不指定则输出到终端。其余参数原样转交模型切片脚本，入口保留其退出码。

各模型切片脚本均支持 `--help`、`--studio`、`--profiles` 和 `--output-dir`。默认安装路径为 macOS 的 `/Applications/BambuStudio.app/`；其它安装位置需显式指定。工作区不得覆盖源码、模型产物或站点。

三种模式共用文件选择与工艺配置：

- 普通模式准备配置并运行切片，保存 3MF、G-code、预览、日志和 `slicing-validation.json`。
- `--prepare-only` 仅生成配置、输入指纹和命令数组，不启动 Studio。
- `--collect-only` 复核准备时的模型与配置指纹，以及已有切片的配置、归档几何和专项检查；不改写配置、不启动 Studio。它与 `--prepare-only` 互斥。

工作区中的 `slicing-inputs.json` 绑定源文件、工艺声明和解析后的三个配置。收集时缺失或不匹配须重新准备并切片。车模允许收集已准备文件的子集。

| 模型 ID | 默认工作区 | 工艺与专项检查 |
| --- | --- | --- |
| `fidget-button-fdm` | `tmp/fidget-button-slicing/` | PLA Tough+，0.16 mm；弹臂、根部、接触垫、锁紧凸台和自由端间隙 |
| `keyboard-fidget-fdm` | `tmp/keyboard-fidget-slicing/` | PLA Tough+，0.20 mm；弹臂、螺钉、导向、固定座、凸轮和装拆材料包络 |
| `retractable-shuriken-fdm` | `tmp/retractable-shuriken-slicing/` | PLA Basic，0.20 mm；弹舌、钩柱、钩头及销柱路径 |
| `star-chain-fdm` | `tmp/star-chain-slicing/` | PLA Basic，0.20 mm；卡位、固定端防脱、粗榫支承和锁销孔 |
| `volvo-xc60-2022` | `tmp/xc60-slicing/` | PLA Basic，0.16 mm、树状支撑；`--only <文件名...>` 选择打印盘，未知文件名报错，子集报告为 `partial` |

各模型的 `slicing.json` 保存预设名称、覆盖参数、排版策略及归档配置核对项；文件选择与专项检查留在 `src/slice.py`。`tools/slicing.py` 管理配置和执行流程，`tools/slicing_geometry.py` 共用 3MF 几何核对、模态 G-code 解析及材料包络。归档几何核对容差由各模型切片脚本指定。G-code 解析支持绝对／相对坐标与挤出、位置重置、直线及 I/J 或 R 圆弧；检查层范围由模型控制。

直接切片时保存 `studio.log`。收集已有切片时，软件版本使用原日志；手里剑也读取并核对 G-code 头部，不以当前安装版本代替原生产版本。

模型变化后需重新切片；切片代码与结果不参与构建缓存或站点发布。

## 报告复核

- 几何报告 `build/models/<ID>/validation.json` 的 `files` 记录最终文件尺寸、单位、用途及 SHA-256；专项结论在模型生成的附加报告中。构建流程同时校验源码与产物指纹。
- 检查失败可能保留旧报告，须先核对输入指纹。切片报告的 `source_sha256` 及各盘 `sha256` 应与当前构建文件一致；同时核对 `status`、配置、各盘 `warning`、CLI 诊断和关键路径。`complete` 不表示没有警告，`partial` 仅覆盖所选文件。`physical_print_test` 为脚本写入的占位字段，不作为用户实物反馈；实际打印效果以用户反馈为准。
- `--collect-only` 不重新生成刀路，只复核已有切片。输入变化或归档几何不匹配时须重新切片。
- 日志提示保留在本地报告中；影响打印成形的风险同时写入模型说明。
