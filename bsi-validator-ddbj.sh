#!/bin/bash
set -e

# ==========================================
# BSI Validator (DDBJ) Container Wrapper
# ==========================================

# GitHub等で公開する際は "ghcr.io/ddbj/bsi-validator:v1.0.0-beta" 等に変更
IMAGE="localhost/bsi-validator:v1.0.0-beta"

TARGET_PATH=""
OUT_PATH=""
ARGS=()

# ホストのパスを絶対パスに変換するヘルパー関数
get_abs_path() {
    local target="$1"
    if [ -d "$target" ]; then
        echo "$(cd "$target" && pwd)"
    else
        echo "$(cd "$(dirname "$target")" && pwd)/$(basename "$target")"
    fi
}

# 1. 引数解析（ターゲットと出力先を抜き出す）
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--out-dir)
            if [ -z "$2" ]; then
                echo "[ERROR] --out-dir requires a directory path."
                exit 1
            fi
            OUT_PATH="$2"
            # コンテナ内では強制的に /out にマウントして出力させる
            ARGS+=("-o" "/out")
            shift 2
            ;;
        -h|--help)
            # ヘルプの場合はマウントなしで実行して終了
            if command -v podman &> /dev/null; then
                podman run --rm "$IMAGE" ddbj --help
            elif command -v docker &> /dev/null; then
                docker run --rm "$IMAGE" ddbj --help
            fi
            exit 0
            ;;
        -*)
            ARGS+=("$1")
            shift
            ;;
        *)
            # オプション以外の最初の引数をターゲット（入力）とみなす
            if [ -z "$TARGET_PATH" ]; then
                TARGET_PATH="$1"
            else
                ARGS+=("$1")
            fi
            shift
            ;;
    esac
done

MOUNT_OPTS=()

# 2. ターゲット（入力）ディレクトリ/ファイルのマウント設定
if [ -n "$TARGET_PATH" ]; then
    if [ -d "$TARGET_PATH" ]; then
        ABS_TARGET=$(get_abs_path "$TARGET_PATH")
        MOUNT_OPTS+=("-v" "${ABS_TARGET}:/data:ro")
        ARGS=("/data" "${ARGS[@]}")
    elif [ -f "$TARGET_PATH" ]; then
        ABS_TARGET_DIR=$(get_abs_path "$(dirname "$TARGET_PATH")")
        TARGET_FILE=$(basename "$TARGET_PATH")
        # ファイルが指定された場合は、その親ディレクトリごとマウントする（FASTAも読み込むため）
        MOUNT_OPTS+=("-v" "${ABS_TARGET_DIR}:/data:ro")
        ARGS=("/data/${TARGET_FILE}" "${ARGS[@]}")
    else
        echo "[ERROR] Input target not found: $TARGET_PATH"
        exit 1
    fi
else
    # 引数なしの場合はカレントディレクトリをマウント
    MOUNT_OPTS+=("-v" "$(pwd):/data:ro")
    ARGS=("/data" "${ARGS[@]}")
fi

# 3. 出力ディレクトリのマウント設定
if [ -n "$OUT_PATH" ]; then
    mkdir -p "$OUT_PATH"
    ABS_OUT=$(get_abs_path "$OUT_PATH")
    MOUNT_OPTS+=("-v" "${ABS_OUT}:/out")
fi

# NCBI API Key が環境変数にあれば引き継ぐ
if [ -n "$NCBI_API_KEY" ]; then
    MOUNT_OPTS+=("-e" "NCBI_API_KEY=${NCBI_API_KEY}")
fi

# 4. 実行エンジンの判定と実行
if command -v podman &> /dev/null; then
    echo "=> Running via Podman..."
    podman run --rm "${MOUNT_OPTS[@]}" "$IMAGE" ddbj "${ARGS[@]}"

elif command -v docker &> /dev/null; then
    echo "=> Running via Docker..."
    # Dockerはroot権限でファイルを作ってしまう問題を防ぐためユーザーIDを指定
    docker run --rm -u "$(id -u):$(id -g)" "${MOUNT_OPTS[@]}" "$IMAGE" ddbj "${ARGS[@]}"

elif command -v singularity &> /dev/null; then
    echo "=> Running via Singularity..."
    # Singularity 向けのマウント構築
    SING_MOUNTS=""
    if [ -n "$TARGET_PATH" ]; then
        if [ -d "$TARGET_PATH" ]; then
            SING_MOUNTS="--bind ${ABS_TARGET}:/data"
        else
            SING_MOUNTS="--bind ${ABS_TARGET_DIR}:/data"
        fi
    else
        SING_MOUNTS="--bind $(pwd):/data"
    fi
    
    if [ -n "$OUT_PATH" ]; then
        SING_MOUNTS="${SING_MOUNTS} --bind ${ABS_OUT}:/out"
    fi
    
    if [ -n "$NCBI_API_KEY" ]; then
        export SINGULARITYENV_NCBI_API_KEY="$NCBI_API_KEY"
    fi
    
    singularity exec $SING_MOUNTS "docker://${IMAGE}" python /app/main.py ddbj "${ARGS[@]}"
else
    echo "[ERROR] Neither Podman, Docker, nor Singularity is installed on your system."
    exit 1
fi