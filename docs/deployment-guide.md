# AI 短剧自动化生产平台 - 部署指南

本指南详细说明如何在生产环境中部署 AI 短剧自动化生产平台。

## 目录

- [部署方式](#部署方式)
- [前置准备](#前置准备)
- [Docker 部署（推荐）](#docker-部署推荐)
- [裸机部署](#裸机部署)
- [配置指南](#配置指南)
- [运维指南](#运维指南)
- [性能调优](#性能调优)
- [常见问题](#常见问题)

---

## 部署方式

本平台支持两种部署方式：

| 部署方式 | 优点 | 缺点 | 适用场景 |
|---------|------|------|---------|
| **Docker 部署** | 环境隔离、易于管理、快速部署 | 需要学习 Docker | 推荐用于生产环境 |
| **裸机部署** | 性能最优、灵活配置 | 环境配置复杂 | 适合开发和测试 |

---

## 前置准备

### 1. 系统要求

- **操作系统**：Ubuntu 22.04 LTS（推荐）或 CentOS 8+
- **CPU**：8 核心以上
- **内存**：32GB 以上
- **GPU**：NVIDIA RTX 3090/4090（24GB 显存）
- **存储**：100GB+ SSD（推荐 NVMe）
- **网络**：100Mbps+ 带宽

### 2. 安装依赖

#### 安装 Docker 和 Docker Compose

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | bash

# 启动 Docker 服务
sudo systemctl start docker
sudo systemctl enable docker

# 安装 Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 验证安装
docker --version
docker-compose --version
```

#### 安装 NVIDIA Docker（GPU 支持）

```bash
# 添加 NVIDIA Docker 仓库
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# 安装 NVIDIA Docker
sudo apt-get update
sudo apt-get install -y nvidia-docker2

# 重启 Docker 服务
sudo systemctl restart docker

# 验证 GPU 支持
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### 3. 下载项目代码

```bash
# 克隆仓库
git clone https://github.com/your-org/ai-short-drama-production.git
cd ai-short-drama-production

# 或下载发布版本
wget https://github.com/your-org/ai-short-drama-production/archive/v1.0.0.tar.gz
tar -xzf v1.0.0.tar.gz
cd ai-short-drama-production-1.0.0
```

### 4. 下载 AI 模型

参考 [模型部署指南](model-deployment-guide.md) 下载所有必需的 AI 模型。

```bash
# 使用自动下载脚本
bash scripts/download_models.sh

# 验证模型文件
ls -lh models/qwen/
ls -lh models/sdxl/
ls -lh models/svd/
```

---

## Docker 部署（推荐）

### 1. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置文件
nano .env
```

**必需配置项**：

```bash
# JWT 密钥（生成随机密钥）
JWT_SECRET_KEY=$(openssl rand -hex 32)
ENCRYPTION_KEY=$(openssl rand -hex 32)

# TTS API 密钥（从 MiMo 平台获取）
TTS_API_KEY=your_mimo_api_key_here

# 数据库配置（可选，默认使用 SQLite）
# DATABASE_URL=postgresql://user:password@postgres:5432/short_drama

# Redis 配置
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# ComfyUI 配置
COMFYUI_BASE_URL=http://comfyui:8188

# 模型路径
LLM_MODEL_PATH=./models/qwen/qwen2.5-14b-instruct-q4_k_m.gguf
SVD_MODEL_PATH=./models/svd/svd_xt.safetensors

# GPU 配置
LLM_N_GPU_LAYERS=20
GPU_MEMORY_FRACTION=0.95
```

### 2. 构建 Docker 镜像

```bash
# 构建镜像
docker-compose build

# 查看镜像
docker images | grep short-drama
```

### 3. 启动服务

```bash
# 启动所有服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

### 4. 验证部署

```bash
# 检查 API 健康状态
curl http://localhost:8000/health

# 检查 API 文档
curl http://localhost:8000/docs

# 检查 ComfyUI
curl http://localhost:8188/

# 检查 Redis
redis-cli ping
```

### 5. 创建管理员用户

```bash
# 进入 API 容器
docker-compose exec api bash

# 创建管理员用户
python -c "
from src.database.session import get_db_session
from src.database.models import User
from src.api.auth import hash_password

db = next(get_db_session())
admin = User(
    username='admin',
    email='admin@example.com',
    hashed_password=hash_password('admin123'),
    is_active=1
)
db.add(admin)
db.commit()
print('Admin user created: admin / admin123')
"

# 退出容器
exit
```

---

## 裸机部署

### 1. 安装 Python 和依赖

```bash
# 安装 Python 3.10
sudo apt-get update
sudo apt-get install -y python3.10 python3.10-venv python3-pip

# 创建虚拟环境
python3.10 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 安装系统依赖

```bash
# 安装 FFmpeg
sudo apt-get install -y ffmpeg

# 安装 Redis
sudo apt-get install -y redis-server
sudo systemctl start redis
sudo systemctl enable redis

# 安装 PostgreSQL（可选）
sudo apt-get install -y postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

### 3. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置文件
nano .env
```

**裸机部署配置**：

```bash
# 数据库配置（使用 SQLite）
DATABASE_URL=sqlite:///./short_drama.db

# Redis 配置
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# ComfyUI 配置
COMFYUI_BASE_URL=http://localhost:8188

# API 配置
API_HOST=0.0.0.0
API_PORT=8000
```

### 4. 初始化数据库

```bash
# 创建数据库表
python -c "
from src.database.session import engine
from src.database.models import Base
Base.metadata.create_all(engine)
print('Database initialized')
"
```

### 5. 启动 ComfyUI

```bash
# 进入 ComfyUI 目录
cd ComfyUI

# 启动服务
python main.py --listen 0.0.0.0 --port 8188 &

# 返回项目目录
cd ..
```

### 6. 启动 Celery Worker

```bash
# 启动 Worker
celery -A src.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=default,image,video,audio &
```

### 7. 启动 FastAPI 应用

```bash
# 启动 API 服务
python main.py
```

---

## 配置指南

### 环境变量说明

#### 数据库配置

```bash
# SQLite（默认，适合小规模部署）
DATABASE_URL=sqlite:///./short_drama.db

# PostgreSQL（推荐用于生产环境）
DATABASE_URL=postgresql://username:password@host:5432/database
```

#### Redis 配置

```bash
# 本地 Redis
REDIS_URL=redis://localhost:6379/0

# 远程 Redis
REDIS_URL=redis://:password@host:6379/0

# Redis Sentinel
REDIS_URL=redis+sentinel://host:26379/mymaster/0
```

#### API 配置

```bash
# 监听地址和端口
API_HOST=0.0.0.0
API_PORT=8000

# CORS 配置（允许的前端域名）
CORS_ORIGINS=http://localhost:3000,https://yourdomain.com

# API 速率限制
API_RATE_LIMIT=60/minute
```

#### 安全配置

```bash
# JWT 配置
JWT_SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# 加密密钥
ENCRYPTION_KEY=your-encryption-key-here

# 密码策略
MIN_PASSWORD_LENGTH=8
```

#### 模型配置

```bash
# LLM 配置
LLM_MODEL_PATH=./models/qwen/qwen2.5-14b-instruct-q4_k_m.gguf
LLM_N_GPU_LAYERS=20
LLM_N_CTX=4096
LLM_N_THREADS=8

# SVD 配置
SVD_MODEL_PATH=./models/svd/svd_xt.safetensors
SVD_NUM_FRAMES=16
SVD_FPS=8

# TTS 配置
TTS_API_KEY=your_mimo_api_key_here
TTS_BASE_URL=https://mimo.xiaomi.com/api/v2/tts
```

#### Celery 配置

```bash
# Broker 和 Backend
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Worker 配置
CELERY_WORKER_CONCURRENCY=2
CELERY_TASK_TIME_LIMIT=3600
CELERY_TASK_SOFT_TIME_LIMIT=3000
```

### API 密钥获取

#### MiMo-V2-TTS API 密钥

1. 访问 https://mimo.xiaomi.com/
2. 注册账号并登录
3. 进入"API 管理"页面
4. 创建新的 API 密钥
5. 复制密钥到 `.env` 文件的 `TTS_API_KEY`

---

## 运维指南

### 日志管理

#### Docker 部署

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f api
docker-compose logs -f celery-worker
docker-compose logs -f comfyui

# 查看最近 100 行日志
docker-compose logs --tail=100 api

# 导出日志到文件
docker-compose logs > logs/docker-compose.log
```

#### 裸机部署

```bash
# 应用日志
tail -f logs/app.log

# Celery 日志
tail -f logs/celery.log

# ComfyUI 日志
tail -f ComfyUI/comfyui.log
```

### 服务管理

#### Docker 部署

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 重启特定服务
docker-compose restart api

# 查看服务状态
docker-compose ps

# 查看资源使用
docker stats
```

#### 裸机部署

```bash
# 使用 systemd 管理服务
sudo systemctl start short-drama-api
sudo systemctl stop short-drama-api
sudo systemctl restart short-drama-api
sudo systemctl status short-drama-api

# 查看进程
ps aux | grep python
ps aux | grep celery
```

### 数据备份

#### 备份数据库

```bash
# SQLite 备份
cp short_drama.db backups/short_drama_$(date +%Y%m%d).db

# PostgreSQL 备份
pg_dump -U username -d short_drama > backups/short_drama_$(date +%Y%m%d).sql
```

#### 备份存储文件

```bash
# 备份生成的文件
tar -czf backups/storage_$(date +%Y%m%d).tar.gz storage/

# 使用 rsync 增量备份
rsync -avz storage/ /backup/storage/
```

#### 自动备份脚本

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup/short-drama"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份数据库
cp short_drama.db $BACKUP_DIR/db_$DATE.db

# 备份存储文件
tar -czf $BACKUP_DIR/storage_$DATE.tar.gz storage/

# 删除 7 天前的备份
find $BACKUP_DIR -name "*.db" -mtime +7 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
```

### 监控和告警

#### 健康检查

```bash
# API 健康检查
curl http://localhost:8000/health

# Redis 健康检查
redis-cli ping

# ComfyUI 健康检查
curl http://localhost:8188/

# GPU 监控
nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv
```

#### 性能监控

```bash
# CPU 和内存使用
top
htop

# 磁盘使用
df -h
du -sh storage/

# 网络连接
netstat -tunlp | grep 8000
```

---

## 性能调优

### GPU 显存优化

```bash
# 减少 LLM GPU 层数（节省显存）
LLM_N_GPU_LAYERS=15  # 从 20 降到 15

# 降低图像分辨率
# 在 ComfyUI 工作流中设置 width=768, height=512

# 减少视频帧数
SVD_NUM_FRAMES=14  # 从 16 降到 14

# 启用 GPU 缓存清理
ENABLE_GPU_CACHE_CLEAR=true
```

### Celery 任务优化

```bash
# 增加 Worker 并发数（如果 CPU 和内存充足）
CELERY_WORKER_CONCURRENCY=4  # 从 2 增加到 4

# 调整任务超时时间
CELERY_TASK_TIME_LIMIT=3600  # 1 小时
CELERY_TASK_SOFT_TIME_LIMIT=3000  # 50 分钟

# 启用任务优先级
# 在代码中设置任务优先级
```

### 数据库优化

```bash
# PostgreSQL 优化
# 编辑 postgresql.conf

# 增加共享缓冲区
shared_buffers = 4GB

# 增加工作内存
work_mem = 256MB

# 增加维护工作内存
maintenance_work_mem = 1GB

# 启用并行查询
max_parallel_workers_per_gather = 4
```

### 网络优化

```bash
# 启用 HTTP/2
# 在 Nginx 配置中启用

# 启用 Gzip 压缩
# 在 FastAPI 中间件中启用

# 使用 CDN 加速静态文件
# 配置 CDN 域名
```

---

## 常见问题

### 问题 1：Docker 容器无法访问 GPU

**症状**：
```
RuntimeError: CUDA not available
```

**解决方案**：
1. 检查 NVIDIA Docker 是否安装：`nvidia-docker --version`
2. 检查 docker-compose.yml 中的 GPU 配置
3. 重启 Docker 服务：`sudo systemctl restart docker`
4. 验证 GPU 访问：`docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi`

### 问题 2：服务启动失败

**症状**：
```
Error: Connection refused
```

**解决方案**：
1. 检查端口是否被占用：`netstat -tunlp | grep 8000`
2. 检查防火墙设置：`sudo ufw status`
3. 查看服务日志：`docker-compose logs api`
4. 检查环境变量配置：`cat .env`

### 问题 3：数据库连接失败

**症状**：
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**解决方案**：
1. 检查数据库服务是否启动：`docker-compose ps postgres`
2. 检查数据库连接字符串：`.env` 中的 `DATABASE_URL`
3. 检查数据库用户权限
4. 查看数据库日志：`docker-compose logs postgres`

### 问题 4：Celery 任务不执行

**症状**：
- 任务一直处于 PENDING 状态

**解决方案**：
1. 检查 Celery Worker 是否启动：`docker-compose ps celery-worker`
2. 检查 Redis 连接：`redis-cli ping`
3. 查看 Worker 日志：`docker-compose logs celery-worker`
4. 检查任务队列：`celery -A src.tasks.celery_app inspect active`

### 问题 5：磁盘空间不足

**症状**：
```
OSError: [Errno 28] No space left on device
```

**解决方案**：
1. 检查磁盘使用：`df -h`
2. 清理旧的生成文件：`rm -rf storage/projects/*/`
3. 清理 Docker 镜像：`docker system prune -a`
4. 清理日志文件：`rm -rf logs/*.log`
5. 配置日志轮转

---

## 生产环境建议

### 安全加固

1. **使用 HTTPS**
   ```bash
   # 使用 Let's Encrypt 获取 SSL 证书
   sudo apt-get install certbot
   sudo certbot certonly --standalone -d yourdomain.com
   ```

2. **配置防火墙**
   ```bash
   # 只开放必要的端口
   sudo ufw allow 22/tcp    # SSH
   sudo ufw allow 80/tcp    # HTTP
   sudo ufw allow 443/tcp   # HTTPS
   sudo ufw enable
   ```

3. **使用强密码**
   - JWT 密钥至少 32 字符
   - 数据库密码至少 16 字符
   - 定期更换密码

4. **限制 API 访问**
   - 启用速率限制
   - 使用 IP 白名单
   - 启用 CORS 限制

### 高可用部署

1. **负载均衡**
   - 使用 Nginx 或 HAProxy
   - 部署多个 API 实例
   - 配置健康检查

2. **数据库主从复制**
   - 配置 PostgreSQL 主从复制
   - 使用读写分离
   - 定期备份

3. **Redis 集群**
   - 使用 Redis Sentinel
   - 配置主从复制
   - 启用持久化

### 监控和告警

1. **使用 Prometheus + Grafana**
   - 监控 API 性能
   - 监控 GPU 使用率
   - 监控任务队列长度

2. **配置告警规则**
   - CPU 使用率 > 80%
   - 内存使用率 > 90%
   - 磁盘使用率 > 85%
   - API 响应时间 > 5s

---

## 下一步

- 阅读 [模型部署指南](model-deployment-guide.md) 了解模型配置
- 阅读 [用户手册](user-manual.md) 了解如何使用系统
- 阅读 [最佳实践](best-practices.md) 了解性能优化建议
- 阅读 [API 文档](http://localhost:8000/docs) 了解 API 接口

---

**更新日期**：2026-04-29  
**版本**：1.0.0
