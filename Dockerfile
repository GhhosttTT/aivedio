# AI 短剧自动化生产平台 - Dockerfile
# 多阶段构建，优化镜像大小

# ==================== 阶段 1：基础镜像 ====================
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 AS base

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    ffmpeg \
    git \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建工作目录
WORKDIR /app

# ==================== 阶段 2：依赖安装 ====================
FROM base AS dependencies

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip3 install --no-cache-dir -r requirements.txt

# ==================== 阶段 3：应用构建 ====================
FROM dependencies AS application

# 复制应用代码
COPY src/ ./src/
COPY main.py .
COPY .env.example .env

# 创建必要的目录
RUN mkdir -p /app/models \
    /app/storage \
    /app/logs \
    /app/configs

# 设置权限
RUN chmod +x main.py

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["python3", "main.py"]
