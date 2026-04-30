# AI 短剧自动化生产平台 - 前端项目初始化脚本 (PowerShell)

Write-Host "🚀 开始初始化前端项目..." -ForegroundColor Green

# 创建前端目录
New-Item -ItemType Directory -Force -Path "frontend" | Out-Null
Set-Location "frontend"

# 使用 Vite 创建 React + TypeScript 项目
Write-Host "📦 创建 React + TypeScript 项目..." -ForegroundColor Cyan
npm create vite@latest . -- --template react-ts

# 安装依赖
Write-Host "📦 安装项目依赖..." -ForegroundColor Cyan
npm install

# 安装 UI 组件库和工具
Write-Host "📦 安装 Ant Design 和其他依赖..." -ForegroundColor Cyan
npm install antd @ant-design/icons
npm install axios zustand react-router-dom
npm install -D tailwindcss postcss autoprefixer
npm install -D @types/node

# 初始化 Tailwind CSS
Write-Host "🎨 初始化 Tailwind CSS..." -ForegroundColor Cyan
npx tailwindcss init -p

# 创建项目结构
Write-Host "📁 创建项目结构..." -ForegroundColor Cyan
$directories = @(
    "src/api",
    "src/components",
    "src/pages/Login",
    "src/pages/Projects",
    "src/pages/ScriptEditor",
    "src/pages/Production",
    "src/pages/VideoPreview",
    "src/hooks",
    "src/store",
    "src/types",
    "src/utils"
)

foreach ($dir in $directories) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Write-Host "✅ 前端项目初始化完成！" -ForegroundColor Green
Write-Host ""
Write-Host "下一步：" -ForegroundColor Yellow
Write-Host "1. cd frontend"
Write-Host "2. npm run dev"
Write-Host "3. 访问 http://localhost:5173"
