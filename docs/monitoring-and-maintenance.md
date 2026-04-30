# AI 短剧自动化生产平台 - 服务监控和维护指南

本指南详细说明如何监控和维护 AI 短剧自动化生产平台，确保系统稳定运行。

## 目录

- [服务健康检查](#服务健康检查)
- [日志分析](#日志分析)
- [性能监控](#性能监控)
- [备份和恢复](#备份和恢复)
- [扩容指南](#扩容指南)
- [安全加固](#安全加固)
- [故障排查](#故障排查)
- [维护计划](#维护计划)

---

## 服务健康检查

### 1. API 服务健康检查

#### 基本健康检查

```bash
# 检查 API 服务是否运行
curl http://localhost:8000/health

# 预期响应
{
  "status": "healthy",
  "timestamp": "2026-04-29T10:00:00Z",
  "version": "1.0.0"
}
```

#### 详细健康检查脚本

创建 `scripts/health_check.sh`：

```bash
#!/bin/bash

# 颜色定义
GREEN='\033[0:32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo "=== AI 短剧平台健康检查 ==="
echo ""

# 检查 API 服务
echo -n "检查 API 服务... "
if curl -s http://localhost:8000/health > /dev/null; then
    echo -e "${GREEN}✓ 正常${NC}"
else
    echo -e "${RED}✗ 异常${NC}"
fi

# 检查 Redis
echo -n "检查 Redis... "
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓ 正常${NC}"
else
    echo -e "${RED}✗ 异常${NC}"
fi

# 检查 ComfyUI
echo -n "检查 ComfyUI... "
if curl -s http://localhost:8188/ > /dev/null; then
    echo -e "${GREEN}✓ 正常${NC}"
else
    echo -e "${RED}✗ 异常${NC}"
fi

# 检查 Celery Worker
echo -n "检查 Celery Worker... "
WORKER_COUNT=$(celery -A src.tasks.celery_app inspect active 2>/dev/null | grep -c "worker")
if [ "$WORKER_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ 正常 ($WORKER_COUNT 个 Worker)${NC}"
else
    echo -e "${RED}✗ 异常${NC}"
fi

# 检查 GPU
echo -n "检查 GPU... "
if nvidia-smi > /dev/null 2>&1; then
    GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader)
    echo -e "${GREEN}✓ 正常 (温度: ${GPU_TEMP}°C, 显存: ${GPU_MEM})${NC}"
else
    echo -e "${YELLOW}⚠ GPU 不可用${NC}"
fi

# 检查磁盘空间
echo -n "检查磁盘空间... "
DISK_USAGE=$(df -h . | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 85 ]; then
    echo -e "${GREEN}✓ 正常 (使用率: ${DISK_USAGE}%)${NC}"
else
    echo -e "${YELLOW}⚠ 磁盘空间不足 (使用率: ${DISK_USAGE}%)${NC}"
fi

echo ""
echo "=== 健康检查完成 ==="
```

### 2. 服务状态监控

#### Docker 部署

```bash
# 查看所有服务状态
docker-compose ps

# 查看服务资源使用
docker stats

# 查看特定服务日志
docker-compose logs -f api
docker-compose logs -f celery-worker
docker-compose logs -f comfyui
```

#### 裸机部署

```bash
# 查看进程状态
ps aux | grep python
ps aux | grep celery
ps aux | grep redis

# 查看端口占用
netstat -tunlp | grep 8000  # API
netstat -tunlp | grep 6379  # Redis
netstat -tunlp | grep 8188  # ComfyUI

# 查看系统资源
top
htop
```

### 3. 自动化健康检查

#### 使用 systemd 定时器

创建 `/etc/systemd/system/short-drama-health-check.service`：

```ini
[Unit]
Description=Short Drama Platform Health Check
After=network.target

[Service]
Type=oneshot
User=your-user
WorkingDirectory=/path/to/project
ExecStart=/path/to/project/scripts/health_check.sh
```

创建 `/etc/systemd/system/short-drama-health-check.timer`：

```ini
[Unit]
Description=Run Short Drama Health Check Every 5 Minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

启用定时器：

```bash
sudo systemctl daemon-reload
sudo systemctl enable short-drama-health-check.timer
sudo systemctl start short-drama-health-check.timer
```

---

## 日志分析

### 1. 日志位置

#### Docker 部署

```bash
# API 日志
docker-compose logs api

# Celery Worker 日志
docker-compose logs celery-worker

# ComfyUI 日志
docker-compose logs comfyui

# Redis 日志
docker-compose logs redis
```

#### 裸机部署

```
logs/
├── app.log          # API 应用日志
├── celery.log       # Celery Worker 日志
├── error.log        # 错误日志
└── access.log       # API 访问日志
```

### 2. 日志级别

日志级别从低到高：
- **DEBUG**：调试信息
- **INFO**：一般信息
- **WARNING**：警告信息
- **ERROR**：错误信息
- **CRITICAL**：严重错误

### 3. 日志分析工具

#### 查看实时日志

```bash
# 查看最新日志
tail -f logs/app.log

# 查看最近 100 行
tail -n 100 logs/app.log

# 查看特定时间段的日志
grep "2026-04-29 10:" logs/app.log
```

#### 搜索错误日志

```bash
# 搜索错误
grep "ERROR" logs/app.log

# 搜索特定错误
grep "ConnectionError" logs/app.log

# 统计错误数量
grep -c "ERROR" logs/app.log

# 查看错误上下文
grep -A 5 -B 5 "ERROR" logs/app.log
```

#### 分析 API 访问日志

```bash
# 统计请求数
wc -l logs/access.log

# 统计 HTTP 状态码
awk '{print $9}' logs/access.log | sort | uniq -c

# 统计最常访问的端点
awk '{print $7}' logs/access.log | sort | uniq -c | sort -rn | head -10

# 统计响应时间
awk '{sum+=$10; count++} END {print "平均响应时间:", sum/count, "ms"}' logs/access.log
```

### 4. 日志轮转

#### 配置 logrotate

创建 `/etc/logrotate.d/short-drama`：

```
/path/to/project/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 your-user your-group
    sharedscripts
    postrotate
        systemctl reload short-drama-api
    endscript
}
```

测试配置：

```bash
sudo logrotate -d /etc/logrotate.d/short-drama
```

### 5. 日志聚合

#### 使用 ELK Stack（可选）

1. **Elasticsearch**：存储日志
2. **Logstash**：收集和处理日志
3. **Kibana**：可视化日志

配置 Logstash：

```yaml
input {
  file {
    path => "/path/to/project/logs/*.log"
    start_position => "beginning"
  }
}

filter {
  grok {
    match => { "message" => "%{TIMESTAMP_ISO8601:timestamp} %{LOGLEVEL:level} %{GREEDYDATA:message}" }
  }
}

output {
  elasticsearch {
    hosts => ["localhost:9200"]
    index => "short-drama-%{+YYYY.MM.dd}"
  }
}
```

---

## 性能监控

### 1. Prometheus + Grafana 监控

#### 安装 Prometheus

```bash
# 下载 Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar -xzf prometheus-2.45.0.linux-amd64.tar.gz
cd prometheus-2.45.0.linux-amd64
```

#### 配置 Prometheus

创建 `prometheus.yml`：

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'short-drama-api'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']

  - job_name: 'redis-exporter'
    static_configs:
      - targets: ['localhost:9121']

  - job_name: 'nvidia-gpu'
    static_configs:
      - targets: ['localhost:9445']
```

启动 Prometheus：

```bash
./prometheus --config.file=prometheus.yml
```

#### 安装 Grafana

```bash
# Ubuntu/Debian
sudo apt-get install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -
sudo apt-get update
sudo apt-get install grafana

# 启动 Grafana
sudo systemctl start grafana-server
sudo systemctl enable grafana-server
```

访问 Grafana：http://localhost:3000（默认用户名/密码：admin/admin）

#### 配置 Grafana 仪表板

1. 添加 Prometheus 数据源
2. 导入仪表板模板
3. 创建自定义面板

**推荐监控指标**：
- API 请求速率
- API 响应时间（P50、P95、P99）
- 错误率
- Celery 任务队列长度
- Celery 任务执行时间
- GPU 使用率和显存
- CPU 和内存使用率
- 磁盘 I/O
- 网络流量

### 2. GPU 监控

#### 使用 nvidia-smi

```bash
# 实时监控
watch -n 1 nvidia-smi

# 查询特定指标
nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv

# 持续记录到文件
nvidia-smi --query-gpu=timestamp,name,temperature.gpu,utilization.gpu,memory.used --format=csv -l 5 >> gpu_metrics.csv
```

#### 使用 NVIDIA DCGM Exporter（Prometheus）

```bash
# 安装 DCGM Exporter
docker run -d --gpus all --rm -p 9400:9400 nvidia/dcgm-exporter:latest
```

### 3. 应用性能监控（APM）

#### 使用 New Relic（可选）

```bash
# 安装 New Relic Python Agent
pip install newrelic

# 配置
newrelic-admin generate-config YOUR_LICENSE_KEY newrelic.ini

# 启动应用
NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program python main.py
```

#### 使用 Sentry（错误追踪）

```bash
# 安装 Sentry SDK
pip install sentry-sdk

# 在代码中配置
import sentry_sdk
sentry_sdk.init(
    dsn="YOUR_SENTRY_DSN",
    traces_sample_rate=1.0
)
```

---

## 备份和恢复

### 1. 数据库备份

#### SQLite 备份

```bash
# 手动备份
cp short_drama.db backups/short_drama_$(date +%Y%m%d_%H%M%S).db

# 自动备份脚本
#!/bin/bash
BACKUP_DIR="/backup/short-drama/db"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
cp short_drama.db $BACKUP_DIR/short_drama_$DATE.db
# 删除 30 天前的备份
find $BACKUP_DIR -name "*.db" -mtime +30 -delete
```

#### PostgreSQL 备份

```bash
# 手动备份
pg_dump -U username -d short_drama > backups/short_drama_$(date +%Y%m%d_%H%M%S).sql

# 自动备份脚本
#!/bin/bash
BACKUP_DIR="/backup/short-drama/db"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
pg_dump -U username -d short_drama | gzip > $BACKUP_DIR/short_drama_$DATE.sql.gz
# 删除 30 天前的备份
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete
```

### 2. 存储文件备份

```bash
# 增量备份（使用 rsync）
rsync -avz --delete storage/ /backup/short-drama/storage/

# 完整备份（使用 tar）
tar -czf backups/storage_$(date +%Y%m%d).tar.gz storage/

# 使用 rclone 备份到云存储
rclone sync storage/ remote:short-drama/storage/
```

### 3. 配置文件备份

```bash
# 备份配置文件
tar -czf backups/config_$(date +%Y%m%d).tar.gz .env docker-compose.yml configs/
```

### 4. 自动化备份

#### 使用 cron 定时备份

```bash
# 编辑 crontab
crontab -e

# 添加定时任务
# 每天凌晨 2 点备份数据库
0 2 * * * /path/to/project/scripts/backup_database.sh

# 每天凌晨 3 点备份存储文件
0 3 * * * /path/to/project/scripts/backup_storage.sh

# 每周日凌晨 4 点备份配置文件
0 4 * * 0 /path/to/project/scripts/backup_config.sh
```

### 5. 数据恢复

#### SQLite 恢复

```bash
# 停止服务
docker-compose down

# 恢复数据库
cp backups/short_drama_20260429.db short_drama.db

# 启动服务
docker-compose up -d
```

#### PostgreSQL 恢复

```bash
# 停止服务
docker-compose down

# 恢复数据库
psql -U username -d short_drama < backups/short_drama_20260429.sql

# 启动服务
docker-compose up -d
```

#### 存储文件恢复

```bash
# 停止服务
docker-compose down

# 恢复存储文件
rm -rf storage/
tar -xzf backups/storage_20260429.tar.gz

# 启动服务
docker-compose up -d
```

---

## 扩容指南

### 1. 垂直扩容（升级硬件）

#### 增加 CPU 和内存

```bash
# 调整 Celery Worker 并发数
CELERY_WORKER_CONCURRENCY=8  # 从 2 增加到 8

# 重启 Worker
docker-compose restart celery-worker
```

#### 增加 GPU

```bash
# 配置多 GPU
# 在 docker-compose.yml 中
services:
  celery-worker:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['0', '1']  # 使用 GPU 0 和 1
              capabilities: [gpu]
```

### 2. 水平扩容（增加实例）

#### 增加 API 实例

```bash
# 使用 Nginx 负载均衡
upstream short_drama_api {
    server api1:8000;
    server api2:8000;
    server api3:8000;
}

server {
    listen 80;
    location / {
        proxy_pass http://short_drama_api;
    }
}
```

#### 增加 Celery Worker

```bash
# 启动多个 Worker
docker-compose up -d --scale celery-worker=4
```

#### 配置 Redis 集群

```bash
# 使用 Redis Sentinel 实现高可用
# 配置 sentinel.conf
sentinel monitor mymaster 127.0.0.1 6379 2
sentinel down-after-milliseconds mymaster 5000
sentinel parallel-syncs mymaster 1
sentinel failover-timeout mymaster 10000
```

### 3. 数据库扩容

#### PostgreSQL 主从复制

```yaml
# docker-compose.yml
services:
  postgres-master:
    image: postgres:15
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: short_drama
    volumes:
      - postgres-master-data:/var/lib/postgresql/data

  postgres-slave:
    image: postgres:15
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: short_drama
      POSTGRES_MASTER_SERVICE_HOST: postgres-master
    volumes:
      - postgres-slave-data:/var/lib/postgresql/data
```

### 4. 存储扩容

#### 使用对象存储（S3/MinIO）

```python
# 配置 S3 存储
import boto3

s3_client = boto3.client(
    's3',
    endpoint_url='https://s3.amazonaws.com',
    aws_access_key_id='YOUR_ACCESS_KEY',
    aws_secret_access_key='YOUR_SECRET_KEY'
)

# 上传文件
s3_client.upload_file('local_file.mp4', 'bucket-name', 'remote_file.mp4')
```

---

## 安全加固

### 1. 网络安全

#### 配置防火墙

```bash
# 使用 ufw
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# 限制 SSH 访问
sudo ufw allow from 192.168.1.0/24 to any port 22
```

#### 使用 fail2ban 防止暴力破解

```bash
# 安装 fail2ban
sudo apt-get install fail2ban

# 配置 /etc/fail2ban/jail.local
[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600
```

### 2. 应用安全

#### 启用 HTTPS

```bash
# 使用 Let's Encrypt
sudo certbot --nginx -d yourdomain.com

# 自动续期
sudo certbot renew --dry-run
```

#### 配置 Nginx 安全头

```nginx
server {
    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # 隐藏版本号
    server_tokens off;
}
```

#### 限制文件上传大小

```python
# FastAPI 配置
from fastapi import FastAPI, UploadFile, File

app = FastAPI()

@app.post("/upload")
async def upload_file(file: UploadFile = File(..., max_length=100*1024*1024)):  # 100MB
    pass
```

### 3. 数据安全

#### 加密敏感数据

```python
from cryptography.fernet import Fernet

# 生成密钥
key = Fernet.generate_key()
cipher = Fernet(key)

# 加密
encrypted = cipher.encrypt(b"sensitive data")

# 解密
decrypted = cipher.decrypt(encrypted)
```

#### 定期更新密钥

```bash
# 更新 JWT 密钥
JWT_SECRET_KEY=$(openssl rand -hex 32)

# 更新加密密钥
ENCRYPTION_KEY=$(openssl rand -hex 32)
```

### 4. 访问控制

#### 配置 IP 白名单

```nginx
# Nginx 配置
location /admin {
    allow 192.168.1.0/24;
    deny all;
}
```

#### 实施最小权限原则

```bash
# 创建专用用户
sudo useradd -r -s /bin/false short-drama

# 设置文件权限
sudo chown -R short-drama:short-drama /path/to/project
sudo chmod 750 /path/to/project
```

---

## 故障排查

### 1. 常见问题

#### API 服务无响应

```bash
# 检查服务状态
docker-compose ps api

# 查看日志
docker-compose logs --tail=100 api

# 检查端口
netstat -tunlp | grep 8000

# 重启服务
docker-compose restart api
```

#### Celery 任务不执行

```bash
# 检查 Worker 状态
celery -A src.tasks.celery_app inspect active

# 检查队列长度
celery -A src.tasks.celery_app inspect reserved

# 清空队列
celery -A src.tasks.celery_app purge

# 重启 Worker
docker-compose restart celery-worker
```

#### GPU 显存不足

```bash
# 清理 GPU 缓存
nvidia-smi --gpu-reset

# 调整模型配置
LLM_N_GPU_LAYERS=15  # 减少 GPU 层数
SVD_NUM_FRAMES=14    # 减少视频帧数

# 重启服务
docker-compose restart
```

### 2. 性能问题

#### API 响应慢

```bash
# 检查数据库查询
# 启用 SQL 日志
DATABASE_ECHO=true

# 添加索引
CREATE INDEX idx_project_user_id ON projects(user_id);
CREATE INDEX idx_scene_project_id ON scenes(project_id);

# 优化查询
# 使用 select_related 和 prefetch_related
```

#### 磁盘空间不足

```bash
# 清理旧文件
find storage/ -type f -mtime +30 -delete

# 清理 Docker 镜像
docker system prune -a

# 清理日志
find logs/ -name "*.log" -mtime +7 -delete
```

---

## 维护计划

### 日常维护（每天）

- [ ] 检查服务健康状态
- [ ] 查看错误日志
- [ ] 监控磁盘空间
- [ ] 检查 GPU 温度和使用率

### 每周维护

- [ ] 审查性能指标
- [ ] 检查备份完整性
- [ ] 清理临时文件
- [ ] 更新安全补丁

### 每月维护

- [ ] 数据库优化（VACUUM、ANALYZE）
- [ ] 日志归档
- [ ] 性能测试
- [ ] 安全审计

### 每季度维护

- [ ] 系统升级
- [ ] 容量规划
- [ ] 灾难恢复演练
- [ ] 文档更新

---

**更新日期**：2026-04-29  
**版本**：1.0.0
