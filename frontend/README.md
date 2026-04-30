# AI 短剧自动化生产平台 - 前端项目

## 🎨 设计理念

基于 **frontend-design** 技能打造的现代化、专业级前端界面：

### 美学方向
- **深色科技感主题**：深色背景 + 渐变光效，营造专业沉浸式体验
- **流畅动画**：使用 Framer Motion 实现页面切换和元素动画
- **实时反馈**：WebSocket 实时推送生产进度
- **卡片式布局**：清晰展示项目和分镜信息

### 核心特色
- ✨ 渐变色彩系统（紫色 → 蓝色）
- 🎭 玻璃态效果（backdrop-blur）
- 🌊 流畅的页面过渡动画
- 📊 实时进度可视化
- 🎯 响应式设计（移动端友好）

## 📁 项目结构

```
frontend/
├── src/
│   ├── pages/              # 页面组件
│   │   ├── ProjectList.tsx      # 项目列表页
│   │   └── ProjectDetail.tsx    # 项目详情页
│   ├── components/         # 通用组件
│   │   ├── ScriptPreview.tsx    # 剧本预览组件
│   │   └── ProductionProgress.tsx # 生产进度组件
│   ├── hooks/              # 自定义 Hooks
│   │   └── useWebSocket.ts      # WebSocket Hook
│   ├── api/                # API 客户端
│   │   └── client.ts            # API 请求封装
│   ├── types/              # TypeScript 类型定义
│   │   └── index.ts             # 通用类型
│   ├── App.tsx             # 应用入口
│   └── main.tsx            # 主入口文件
├── package.json
└── README.md
```

## 🚀 技术栈

### 核心框架
- **React 18** - UI 框架
- **TypeScript** - 类型安全
- **Vite** - 构建工具

### UI 库
- **Tailwind CSS** - 样式框架
- **Framer Motion** - 动画库
- **Lucide React** - 图标库

### 状态管理
- **React Hooks** - 本地状态
- **WebSocket** - 实时通信

### HTTP 客户端
- **Axios** - API 请求

## 📄 已创建的页面

### 1. 项目列表页 (`ProjectList.tsx`)

**功能**：
- ✅ 展示所有短剧项目
- ✅ 创建新项目（模态框）
- ✅ 项目状态标签（草稿、生成中、就绪、制作中、已完成、失败）
- ✅ 点击跳转到项目详情
- ✅ 空状态提示

**设计亮点**：
- 渐变背景装饰
- 卡片悬停动画（上浮 + 边框高亮）
- 状态图标和颜色编码
- 创建项目模态框（玻璃态效果）

### 2. 项目详情页 (`ProjectDetail.tsx`)

**功能**：
- ✅ 查看项目信息
- ✅ 标签页切换（剧本预览 / 制作进度）
- ✅ 生成剧本按钮
- ✅ 开始制作按钮
- ✅ 下载视频按钮

**设计亮点**：
- 面包屑导航
- 动画标签页切换
- 渐变按钮（不同状态不同颜色）

### 3. 剧本预览组件 (`ScriptPreview.tsx`)

**功能**：
- ✅ 展示完整剧本文本
- ✅ 分镜卡片列表
- ✅ 编辑并重新生成单个分镜
- ✅ 显示角色、对话、情感标签
- ✅ 显示图像提示词

**设计亮点**：
- 分镜编号徽章
- 角色和对话标签
- 编辑模式切换
- 重新生成加载动画

### 4. 生产进度组件 (`ProductionProgress.tsx`)

**功能**：
- ✅ 总体进度条（动画）
- ✅ WebSocket 实时连接状态
- ✅ 每个分镜的任务状态（图像、视频、配音、字幕）
- ✅ 取消制作按钮
- ✅ 重试按钮（失败时）
- ✅ 错误信息展示

**设计亮点**：
- 渐变进度条 + 光效动画
- 任务状态网格（颜色编码）
- 实时状态图标（加载、完成、失败）
- WebSocket 连接指示器

## 🔌 API 集成

### API 端点

```typescript
// 项目管理
GET    /api/projects              // 获取项目列表
POST   /api/projects              // 创建项目
GET    /api/projects/:id          // 获取项目详情
PUT    /api/projects/:id          // 更新项目
DELETE /api/projects/:id          // 删除项目

// 剧本生成
POST   /api/projects/:id/generate-script    // 生成剧本
POST   /api/projects/:id/regenerate-scene   // 重新生成分镜

// 生产管理
POST   /api/projects/:id/produce   // 开始生产
POST   /api/projects/:id/cancel    // 取消生产
POST   /api/projects/:id/retry     // 重试生产

// WebSocket
WS     /ws/:project_id             // 实时进度推送
```

### WebSocket 消息格式

```typescript
// 进度更新
{
    type: 'progress',
    progress: 0.45,           // 0-1
    phase: '图像生成中',
    scene_id: 3,
    task_type: 'image',
    status: 'processing'
}

// 完成通知
{
    type: 'completed',
    message: '制作完成'
}

// 错误通知
{
    type: 'error',
    error: '错误信息'
}
```

## 🎨 设计系统

### 颜色方案

```css
/* 主色调 */
--purple-500: #a855f7
--blue-500: #3b82f6
--emerald-500: #10b981
--red-500: #ef4444

/* 背景 */
--slate-950: #020617
--slate-900: #0f172a
--slate-800: #1e293b

/* 文本 */
--white: #ffffff
--slate-300: #cbd5e1
--slate-400: #94a3b8
--slate-500: #64748b
```

### 渐变效果

```css
/* 主渐变 */
from-purple-600 to-blue-600

/* 背景渐变 */
from-slate-950 via-slate-900 to-slate-950

/* 文字渐变 */
from-white via-purple-200 to-blue-200
```

### 动画

```typescript
// 页面进入动画
initial={{ opacity: 0, y: 20 }}
animate={{ opacity: 1, y: 0 }}

// 悬停动画
whileHover={{ y: -8, scale: 1.02 }}
whileTap={{ scale: 0.98 }}

// 列表交错动画
variants={{
    visible: {
        transition: { staggerChildren: 0.1 }
    }
}}
```

## 📦 安装和运行

### 安装依赖

```bash
cd frontend
npm install
```

### 开发模式

```bash
npm run dev
```

### 生产构建

```bash
npm run build
```

### 预览生产构建

```bash
npm run preview
```

## 🔧 配置

### 环境变量

创建 `.env` 文件：

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
```

### Tailwind 配置

```javascript
// tailwind.config.js
module.exports = {
    content: ['./src/**/*.{js,jsx,ts,tsx}'],
    theme: {
        extend: {
            colors: {
                // 自定义颜色
            },
            animation: {
                shimmer: 'shimmer 2s infinite',
            },
            keyframes: {
                shimmer: {
                    '0%, 100%': { transform: 'translateX(-100%)' },
                    '50%': { transform: 'translateX(100%)' },
                },
            },
        },
    },
};
```

## 🎯 下一步开发

### 待实现功能

- [ ] 用户认证和登录页面
- [ ] 视频预览播放器
- [ ] 项目设置页面（配置参数）
- [ ] 批量操作（批量删除、导出）
- [ ] 搜索和过滤功能
- [ ] 深色/浅色主题切换
- [ ] 移动端优化

### 性能优化

- [ ] 代码分割（React.lazy）
- [ ] 图片懒加载
- [ ] 虚拟滚动（长列表）
- [ ] Service Worker（PWA）
- [ ] 缓存策略优化

## 📝 开发规范

### 命名规范
- 组件：PascalCase（`ProjectList.tsx`）
- 函数：camelCase（`loadProjects`）
- 常量：UPPER_SNAKE_CASE（`API_BASE_URL`）

### 注释规范
- 每个组件添加功能说明注释
- 复杂逻辑添加行内注释
- API 函数添加 JSDoc 注释

### 代码风格
- 使用 4 空格缩进
- 使用 TypeScript 类型注解
- 使用 ESLint 和 Prettier

## 🎨 设计资源

- **字体**：系统默认字体栈
- **图标**：Lucide React
- **动画**：Framer Motion
- **颜色**：Tailwind CSS 调色板

## 📚 参考文档

- [React 文档](https://react.dev/)
- [TypeScript 文档](https://www.typescriptlang.org/)
- [Tailwind CSS 文档](https://tailwindcss.com/)
- [Framer Motion 文档](https://www.framer.com/motion/)
- [Vite 文档](https://vitejs.dev/)

---

**设计理念来源**：使用 **frontend-design** 技能创建，遵循现代化、专业级的前端设计原则。
