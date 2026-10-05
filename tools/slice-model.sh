#!/bin/bash
# Unified entry for model audits that invoke BambuStudio.
set -euo pipefail

usage() {
    cat <<'EOF'
用法：tools/slice-model.sh <模型 ID> [--log-file <路径>] [模型切片参数...]
      tools/slice-model.sh --list

调用 BambuStudio 的切片必须在沙盒外执行。
先执行 npm run build，再运行此入口；其余参数原样转交对应模型的 slice.py。
--log-file 合并保存标准输出与错误输出，覆盖旧文件并创建父目录。
相对日志路径以仓库根目录为基准；带空格的路径请加引号。
EOF
}

models=(fidget-button-fdm keyboard-fidget-fdm retractable-shuriken-fdm star-chain-fdm volvo-xc60-2022)
case "${1:-}" in
    --help|-h|'') usage; exit 0 ;;
    --list) printf '%s\n' "${models[@]}"; exit 0 ;;
    fidget-button-fdm|keyboard-fidget-fdm|retractable-shuriken-fdm|star-chain-fdm|volvo-xc60-2022)
        model="$1"; shift ;;
    *) printf '不支持的模型 ID：%s\n' "$1" >&2; usage >&2; exit 2 ;;
esac

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo_dir"
model_args=()
log_file=''
log_seen=false
while (( $# )); do
    case "$1" in
        --log-file)
            if [[ "$log_seen" == true ]]; then
                printf '不能重复指定 --log-file。\n' >&2
                exit 2
            fi
            if (( $# < 2 )) || [[ -z "$2" || "$2" == --* ]]; then
                printf '%s\n' '--log-file 缺少路径。' >&2
                exit 2
            fi
            log_seen=true
            log_file="$2"
            shift 2
            ;;
        *) model_args+=("$1"); shift ;;
    esac
done
if [[ "$log_seen" == true ]]; then
    if ! mkdir -p -- "$(dirname -- "$log_file")"; then
        printf '无法创建日志目录：%s\n' "$log_file" >&2
        exit 1
    fi
    if ! exec 3>"$log_file"; then
        printf '无法打开日志：%s\n' "$log_file" >&2
        exit 1
    fi
    exec 1>&3 2>&1 3>&-
fi
if [[ ! -x "$repo_dir/.venv/bin/python" ]]; then
    printf '缺少 .venv/bin/python，请按开发指南安装项目依赖。\n' >&2
    exit 1
fi
exec "$repo_dir/.venv/bin/python" "$repo_dir/tools/run_model.py" \
    "$repo_dir/models/$model/src/slice.py" ${model_args[@]+"${model_args[@]}"}
