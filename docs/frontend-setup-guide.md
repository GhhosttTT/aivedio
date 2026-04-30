# AI 短剧自动化生产平台 - 前端开发指南

## 📋 技术栈

- **框架**: React 18 + TypeScript
- **构建工具**: Vite
- **UI 组件库**: Ant Design 5.x
- **状态管理**: Zustand
- **路由**: React Router v6
- **HTTP 客户端**: Axios
- **WebSocket**: 原生 WebSocket API
- **样式**: CSS Modules + Tailwind CSS

## 🚀 快速开始

### 1. 初始化项目

**Windows (PowerShell)**:
```powershell
.\scripts\init-frontend.ps1
```

**Linux/Mac (Bash)**:
```bash
bash scripts/init-frontend.sh
```

### 2. 手动初始化（如果脚本失败）

```bash
# 创建项目
npm create vite@latest frontend -- --template react-ts
cd frontend

# 安装依赖
npm install

# 安装 UI 库和工具
npm install antd @ant-design/icons axios zustand react-router-dom
npm install -D tailwindcss postcss autoprefixer @types/node

# 初始化 Tailwind
npx tailwindcss init -p
```

### 3. 启动开发服务器

```bash
cd frontend
npm run dev
```

访问 http://localhost:5173

## 📁 项目结构

```
frontend/
├── public/                 # 静态资源
├── src/
│   ├── api/               # API 调用封装
│   │   ├── client.ts      # Axios 客户端配置
│   │   ├── auth.ts        # 认证 API
│   │   ├── projects.ts    # 项目管理 API
│   │   ├── scripts.ts     # 剧本生成 API
│   │   └── tasks.ts       # 任务管理 API
│   │
│   ├── components/        # 通用组件
│   │   ├── Layout/        # 布局组件
│   │   ├── ProjectCard/   # 项目卡片
│   │   ├── ScriptViewer/  # 剧本查看器
│   │   ├── ProgressBar/   # 进度条
│   │   └── VideoPlayer/   # 视频播放器
│   │
│   ├── pages/            # 页面组件
│   │   ├── Login/        # 登录页面
│   │   ├── Projects/     # 项目列表页面
│   │   ├── ScriptEditor/ # 剧本编辑页面
│   │   ├── Production/   # 生产监控页面
│   │   └── VideoPreview/ # 视频预览页面
│   │
│   ├── hooks/            # 自定义 Hooks
│   │   ├── useAuth.ts    # 认证 Hook
│   │   ├── useWebSocket.ts # WebSocket Hook
│   │   └── useProjects.ts  # 项目管理 Hook
│   │
│   ├── store/            # 状态管理
│   │   ├── authStore.ts  # 认证状态
│   │   ├── projectStore.ts # 项目状态
│   │   └── taskStore.ts  # 任务状态
│   │
│   ├── types/            # TypeScript 类型定义
│   │   ├── api.ts        # API 类型
│   │   ├── project.ts    # 项目类型
│   │   ├── script.ts     # 剧本类型
│   │   └── task.ts       # 任务类型
│   │
│   ├── utils/            # 工具函数
│   │   ├── format.ts     # 格式化工具
│   │   ├── storage.ts    # 本地存储
│   │   └── websocket.ts  # WebSocket 工具
│   │
│   ├── App.tsx           # 根组件
│   ├── main.tsx          # 入口文件
│   └── index.css         # 全局样式
│
├── .env.development      # 开发环境变量
├── .env.production       # 生产环境变量
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.js
```

## 🔧 配置文件

### 环境变量 (.env.development)

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
```

### Vite 配置 (vite.config.ts)

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
```

### Tailwind 配置 (tailwind.config.js)

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
  corePlugins: {
    preflight: false, // 禁用 Tailwind 的基础样式，避免与 Ant Design 冲突
  },
}
```

## 📦 核心功能实现

### 1. API 客户端配置

```typescript
// src/api/client.ts
import axios from 'axios'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
})

// 请求拦截器 - 添加 Token
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器 - 处理错误
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      // Token 过期，尝试刷新
      // 实现 Token 刷新逻辑
    }
    return Promise.reject(error)
  }
)

export default apiClient
```

### 2. WebSocket Hook

```typescript
// src/hooks/useWebSocket.ts
import { useEffect, useRef, useState } from 'react'

export const useWebSocket = (projectId: string) => {
  const [messages, setMessages] = useState<any[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const ws = useRef<WebSocket | null>(null)

  useEffect(() => {
    const wsUrl = `${import.meta.env.VITE_WS_BASE_URL}/ws/${projectId}`
    ws.current = new WebSocket(wsUrl)

    ws.current.onopen = () => {
      setIsConnected(true)
      console.log('WebSocket 连接成功')
    }

    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data)
      setMessages((prev) => [...prev, data])
    }

    ws.current.onclose = () => {
      setIsConnected(false)
      console.log('WebSocket 连接关闭')
    }

    return () => {
      ws.current?.close()
    }
  }, [projectId])

  return { messages, isConnected }
}
```

### 3. 认证状态管理

```typescript
// src/store/authStore.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  user: any | null
  token: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isAuthenticated: () => boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      login: async (username, password) => {
        // 调用登录 API
        const response = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        const data = await response.json()
        set({ user: data.user, token: data.access_token })
        localStorage.setItem('access_token', data.access_token)
      },
      logout: () => {
        set({ user: null, token: null })
        localStorage.removeItem('access_token')
      },
      isAuthenticated: () => !!get().token,
    }),
    {
      name: 'auth-storage',
    }
  )
)
```

## 🎨 页面实现示例

### 登录页面

```typescript
// src/pages/Login/index.tsx
import { Form, Input, Button, Card } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useAuthStore } from '@/store/authStore'
import { useNavigate } from 'react-router-dom'

export const LoginPage = () => {
  const login = useAuthStore((state) => state.login)
  const navigate = useNavigate()

  const onFinish = async (values: any) => {
    try {
      await login(values.username, values.password)
      navigate('/projects')
    } catch (error) {
      console.error('登录失败', error)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-100">
      <Card title="AI 短剧生产平台" className="w-96">
        <Form onFinish={onFinish}>
          <Form.Item name="username" rules={[{ required: true }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
```

### 项目列表页面

```typescript
// src/pages/Projects/index.tsx
import { useEffect, useState } from 'react'
import { Card, Button, List, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'

export const ProjectsPage = () => {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    loadProjects()
  }, [])

  const loadProjects = async () => {
    setLoading(true)
    try {
      const response = await apiClient.get('/api/projects')
      setProjects(response.data)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">我的项目</h1>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/projects/new')}
        >
          创建项目
        </Button>
      </div>
      <List
        grid={{ gutter: 16, column: 3 }}
        dataSource={projects}
        loading={loading}
        renderItem={(project: any) => (
          <List.Item>
            <Card
              hoverable
              onClick={() => navigate(`/projects/${project.id}`)}
            >
              <Card.Meta
                title={project.name}
                description={project.theme}
              />
              <div className="mt-4">
                <Tag color={project.status === 'completed' ? 'green' : 'blue'}>
                  {project.status}
                </Tag>
              </div>
            </Card>
          </List.Item>
        )}
      />
    </div>
  )
}
```

## 🔌 API 集成

所有 API 端点已在后端实现，前端只需调用：

- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录
- `POST /api/auth/refresh` - 刷新令牌
- `GET /api/auth/me` - 获取当前用户
- `POST /api/projects` - 创建项目
- `GET /api/projects` - 列出项目
- `GET /api/projects/{id}` - 获取项目详情
- `PUT /api/projects/{id}` - 更新项目
- `DELETE /api/projects/{id}` - 删除项目
- `POST /api/projects/{id}/generate-script` - 生成剧本
- `POST /api/projects/{id}/regenerate-scene` - 重新生成分镜
- `POST /api/projects/{id}/produce` - 提交生产任务
- `GET /api/tasks/{id}/status` - 查询任务状态
- `POST /api/tasks/{id}/cancel` - 取消任务
- `POST /api/tasks/{id}/retry` - 重试任务
- `WS /ws/{project_id}` - WebSocket 实时通信

## 📝 开发建议

1. **组件化开发**: 将可复用的 UI 拆分为独立组件
2. **类型安全**: 充分利用 TypeScript 的类型系统
3. **状态管理**: 使用 Zustand 管理全局状态
4. **错误处理**: 统一处理 API 错误和异常
5. **加载状态**: 为所有异步操作添加加载指示器
6. **响应式设计**: 确保在不同屏幕尺寸下都能正常显示
7. **WebSocket 重连**: 实现 WebSocket 断线重连机制
8. **Token 刷新**: 实现 JWT Token 自动刷新

## 🧪 测试

```bash
# 运行测试
npm run test

# 运行 E2E 测试
npm run test:e2e
```

## 📦 构建和部署

```bash
# 构建生产版本
npm run build

# 预览生产构建
npm run preview
```

构建产物在 `dist/` 目录，可以部署到任何静态文件服务器。

## 🔗 相关文档

- [React 文档](https://react.dev/)
- [Vite 文档](https://vitejs.dev/)
- [Ant Design 文档](https://ant.design/)
- [Zustand 文档](https://github.com/pmndrs/zustand)
- [React Router 文档](https://reactrouter.com/)

---

**最后更新**：2026-04-30  
**更新人**：Kiro AI Assistant
