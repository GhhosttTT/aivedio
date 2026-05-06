# AI 短剧自动化生产平台 - 模型下载脚本 (PowerShell 版本)
# 此脚本用于下载 Stable Diffusion XL 和 Stable Video Diffusion 模型

Write-Host "=== AI 模型下载脚本 ===" -ForegroundColor Green
Write-Host ""

$MODELS_DIR = ".\models"

# 创建目录
if (!(Test-Path "$MODELS_DIR\sdxl")) {
    New-Item -ItemType Directory -Path "$MODELS_DIR\sdxl" -Force | Out-Null
}
if (!(Test-Path "$MODELS_DIR\svd")) {
    New-Item -ItemType Directory -Path "$MODELS_DIR\svd" -Force | Out-Null
}

# 下载文件函数
function Download-File {
    param(
        [string]$url,
        [string]$output
    )
    
    Write-Host "下载: $output" -ForegroundColor Yellow
    Write-Host "URL: $url" -ForegroundColor Gray
    
    try {
        Invoke-WebRequest -Uri $url -OutFile $output -UseBasicParsing
        Write-Host "✓ 下载完成" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "✗ 下载失败: $_" -ForegroundColor Red
        return $false
    }
}

# 下载 Stable Diffusion XL 模型
function Download-SDXL {
    Write-Host ""
    Write-Host "=== 1. 下载 Stable Diffusion XL Base 模型 ===" -ForegroundColor Green
    Write-Host "大小: ~6.9GB" -ForegroundColor Cyan
    Write-Host "用途: 图像生成" -ForegroundColor Cyan
    Write-Host ""
    
    $model_file = "$MODELS_DIR\sdxl\sd_xl_base_1.0.safetensors"
    
    if (Test-Path $model_file) {
        Write-Host "模型文件已存在，跳过下载" -ForegroundColor Yellow
        Write-Host "如需重新下载，请删除: $model_file" -ForegroundColor Yellow
        return $true
    }
    
    $model_url = "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"
    
    Write-Host "提示: 此文件约 6.9GB，下载可能需要较长时间" -ForegroundColor Yellow
    Write-Host ""
    
    if (Download-File -url $model_url -output $model_file) {
        Write-Host "✓ SDXL 模型下载完成" -ForegroundColor Green
        Write-Host ""
        return $true
    }
    else {
        Write-Host "✗ SDXL 模型下载失败" -ForegroundColor Red
        Write-Host "请检查网络连接或手动下载" -ForegroundColor Red
        return $false
    }
}

# 下载 Stable Video Diffusion 模型
function Download-SVD {
    Write-Host ""
    Write-Host "=== 2. 下载 Stable Video Diffusion (SVD) 模型 ===" -ForegroundColor Green
    Write-Host "大小: ~3.8GB" -ForegroundColor Cyan
    Write-Host "用途: 图生视频" -ForegroundColor Cyan
    Write-Host ""
    
    $model_file = "$MODELS_DIR\svd\svd_xt.safetensors"
    
    if (Test-Path $model_file) {
        Write-Host "模型文件已存在，跳过下载" -ForegroundColor Yellow
        Write-Host "如需重新下载，请删除: $model_file" -ForegroundColor Yellow
        return $true
    }
    
    $model_url = "https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors"
    
    Write-Host "提示: 此文件约 3.8GB，下载可能需要较长时间" -ForegroundColor Yellow
    Write-Host ""
    
    if (Download-File -url $model_url -output $model_file) {
        Write-Host "✓ SVD 模型下载完成" -ForegroundColor Green
        Write-Host ""
        return $true
    }
    else {
        Write-Host "✗ SVD 模型下载失败" -ForegroundColor Red
        Write-Host "请检查网络连接或手动下载" -ForegroundColor Red
        return $false
    }
}

# 显示下载摘要
function Show-Summary {
    Write-Host ""
    Write-Host "=== 下载摘要 ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "模型文件位置:" -ForegroundColor Cyan
    Write-Host "  - Qwen2.5-14B: $MODELS_DIR\qwen\qwen2.5-14b-instruct-q4_k_m.gguf (已完成)" -ForegroundColor White
    Write-Host "  - SDXL: $MODELS_DIR\sdxl\sd_xl_base_1.0.safetensors" -ForegroundColor White
    Write-Host "  - SVD: $MODELS_DIR\svd\svd_xt.safetensors" -ForegroundColor White
    Write-Host ""
    Write-Host "总大小: ~18-20GB" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "✓ 所有模型下载完成！" -ForegroundColor Green
    Write-Host ""
    Write-Host "下一步:" -ForegroundColor Yellow
    Write-Host "  1. 检查 .env 文件中的模型路径配置" -ForegroundColor White
    Write-Host "  2. 安装 Python 依赖: pip install -r requirements.txt" -ForegroundColor White
    Write-Host "  3. 安装和配置 ComfyUI" -ForegroundColor White
    Write-Host "  4. 测试模型加载" -ForegroundColor White
    Write-Host ""
}

# 主函数
function Main {
    $success_sdxl = Download-SDXL
    $success_svd = Download-SVD
    
    if ($success_sdxl -and $success_svd) {
        Show-Summary
    }
    else {
        Write-Host ""
        Write-Host "✗ 部分模型下载失败，请检查网络后重试" -ForegroundColor Red
        exit 1
    }
}

# 运行主函数
Main