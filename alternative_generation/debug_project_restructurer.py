#!/usr/bin/env python3
"""
调试项目重构脚本
将 debug_logged_projects 中的项目重构为可运行的全栈项目结构
主要处理 backend.js 和 frontend_with_debug_logs.jsx 文件
"""
import os
import re
import json
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DebugProjectRestructurer:
    """调试项目重构器 - 专门处理带调试日志的项目"""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.project_name = self.project_path.name
        self.restructured_path = self.project_path.parent / f"{self.project_name}_runnable"
        
    def clean_code_content(self, content: str) -> str:
        """清理代码内容，移除markdown标记和多余的格式"""
        # 移除开头的多重代码块标记
        content = re.sub(r'^````[\w\s]*\n', '', content, flags=re.MULTILINE)
        content = re.sub(r'^```[\w\s]*\n', '', content, flags=re.MULTILINE)
        
        # 移除结尾的代码块标记
        content = re.sub(r'\n````$', '', content, flags=re.MULTILINE)
        content = re.sub(r'\n```$', '', content, flags=re.MULTILINE)
        
        # 处理嵌套的代码块标记（文件内容开头可能还有```jsx）
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_if_code_block = False
        
        for i, line in enumerate(lines):
            # 跳过代码块开始标记
            if re.match(r'^```[\w]*$', line.strip()):
                skip_next_if_code_block = True
                continue
            # 跳过代码块结束标记
            elif line.strip() == '```':
                continue
            # 跳过代码块结束标记（在文件末尾）
            elif re.match(r'^```$', line.strip()):
                continue
            else:
                cleaned_lines.append(line)
        
        content = '\n'.join(cleaned_lines)
        
        # 移除文件路径注释
        content = re.sub(r'^// filepath:.*?\n', '', content, flags=re.MULTILINE)
        
        return content.strip()
    
    def extract_files_from_backend(self, content: str) -> Dict[str, str]:
        """从 backend.js 内容中提取文件"""
        files = {}
        
        # 使用 // FILE: filename 格式提取
        pattern = r'// FILE: ([^\n]+)\n(.*?)(?=\n// FILE: |\Z)'
        matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            filename = match.group(1).strip()
            file_content = match.group(2).strip()
            
            # 清理内容：移除代码块标记
            file_content = re.sub(r'^```\w*\n', '', file_content, flags=re.MULTILINE)
            file_content = re.sub(r'\n```$', '', file_content, flags=re.MULTILINE)
            
            if file_content.strip():
                files[filename] = file_content.strip()
                logger.debug(f"📄 提取后端文件: {filename} ({len(file_content)} 字符)")
        
        return files
    
    def extract_react_component_from_jsx(self, content: str) -> str:
        """从 JSX 内容中提取 React 组件代码"""
        # 清理代码内容
        content = self.clean_code_content(content)
        
        # 如果内容包含 FILE: 格式，尝试提取主要的 JSX 部分
        if "// FILE:" in content:
            # 寻找主要的 React 组件部分
            jsx_pattern = r'// FILE: src/App\.jsx\n(.*?)(?=\n// FILE: |\Z)'
            match = re.search(jsx_pattern, content, re.MULTILINE | re.DOTALL)
            if match:
                jsx_content = match.group(1).strip()
                # 清理代码块标记
                jsx_content = re.sub(r'^```\w*\n', '', jsx_content, flags=re.MULTILINE)
                jsx_content = re.sub(r'\n```$', '', jsx_content, flags=re.MULTILINE)
                return jsx_content
        
        # 如果没有找到特定格式，返回整个内容（可能已经是纯JSX）
        return content
    
    def extract_files_from_frontend(self, content: str) -> Dict[str, str]:
        """从前端内容中提取单独的文件"""
        files = {}
        
        # 清理代码内容
        content = self.clean_code_content(content)
        
        # 使用 // FILE: filename 格式提取文件
        pattern = r'// FILE: ([^\n]+)\n(.*?)(?=\n// FILE: |\Z)'
        matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            filename = match.group(1).strip()
            file_content = match.group(2).strip()
            
            # 清理内容：移除代码块标记
            file_content = re.sub(r'^```\w*\n', '', file_content, flags=re.MULTILINE)
            file_content = re.sub(r'\n```$', '', file_content, flags=re.MULTILINE)
            
            if file_content.strip():
                files[filename] = file_content.strip()
                logger.info(f"📄 提取前端文件: {filename} ({len(file_content)} 字符)")
        
        # 如果没有找到标准格式，尝试从整个内容中提取组件
        if not files and content.strip():
            logger.warning("⚠️ 未找到标准文件分隔符，尝试解析整个内容作为组件")
            # 将整个内容作为 App.jsx
            files['src/App.jsx'] = content
        
        return files
    
    def create_backend_structure(self, backend_files: Dict[str, str]) -> bool:
        """创建后端项目结构"""
        backend_dir = self.restructured_path / "backend"
        backend_dir.mkdir(parents=True, exist_ok=True)
        
        # 默认的后端结构
        default_structure = {
            "routes": {},
            "controllers": {},
            "models": {},
            "middleware": {},
            "config": {},
            "data": {}
        }
        
        # 创建目录结构
        for dir_name in default_structure.keys():
            (backend_dir / dir_name).mkdir(exist_ok=True)
        
        # 处理提取的文件
        for filename, content in backend_files.items():
            if filename == "package.json":
                # 更新 package.json
                try:
                    package_data = json.loads(content)
                    # 确保有必要的脚本和依赖
                    if "scripts" not in package_data:
                        package_data["scripts"] = {}
                    package_data["scripts"].update({
                        "start": "node app.js",
                        "dev": "nodemon app.js",
                        "test": "jest"
                    })
                    
                    # 确保有必要的依赖
                    if "dependencies" not in package_data:
                        package_data["dependencies"] = {}
                    
                    required_deps = {
                        "express": "^4.18.2",
                        "cors": "^2.8.5",
                        "dotenv": "^16.0.3",
                        "body-parser": "^1.20.2"
                    }
                    
                    for dep, version in required_deps.items():
                        if dep not in package_data["dependencies"]:
                            package_data["dependencies"][dep] = version
                    
                    # 添加开发依赖
                    if "devDependencies" not in package_data:
                        package_data["devDependencies"] = {}
                    if "nodemon" not in package_data["devDependencies"]:
                        package_data["devDependencies"]["nodemon"] = "^3.0.1"
                    
                    with open(backend_dir / "package.json", 'w', encoding='utf-8') as f:
                        json.dump(package_data, f, indent=2)
                        
                except json.JSONDecodeError:
                    # 如果解析失败，创建默认的 package.json
                    self.create_default_backend_package_json(backend_dir)
                    
            elif filename == ".env":
                with open(backend_dir / ".env", 'w', encoding='utf-8') as f:
                    f.write(content)
                    
            elif filename == "app.js":
                with open(backend_dir / "app.js", 'w', encoding='utf-8') as f:
                    f.write(content)
                    
            elif filename.startswith("routes/"):
                file_path = backend_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
            elif filename.startswith("controllers/"):
                file_path = backend_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
            elif filename.startswith("data/") or filename.startswith("models/"):
                file_path = backend_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
            elif filename.startswith("middleware/"):
                file_path = backend_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
            else:
                # 其他文件直接放在根目录
                with open(backend_dir / filename, 'w', encoding='utf-8') as f:
                    f.write(content)
        
        # 如果没有 package.json，创建默认的
        if not (backend_dir / "package.json").exists():
            self.create_default_backend_package_json(backend_dir)
        
        # 创建 .env.example
        if not (backend_dir / ".env").exists():
            self.create_default_env(backend_dir)
        
        # 创建 .gitignore
        self.create_backend_gitignore(backend_dir)
        
        # 创建 README.md
        self.create_backend_readme(backend_dir)
        
        logger.info(f"✅ 后端结构创建完成: {backend_dir}")
        return True
    
    def create_frontend_structure(self, jsx_content: str) -> bool:
        """创建前端项目结构"""
        frontend_dir = self.restructured_path / "frontend"
        frontend_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建 React 项目结构
        (frontend_dir / "public").mkdir(exist_ok=True)
        (frontend_dir / "src").mkdir(exist_ok=True)
        (frontend_dir / "src" / "components").mkdir(exist_ok=True)
        (frontend_dir / "src" / "styles").mkdir(exist_ok=True)
        
        # 创建 public/index.html
        self.create_index_html(frontend_dir / "public")
        
        # 创建 src/index.js
        self.create_index_js(frontend_dir / "src")
        
        # 解析并分离组件文件
        frontend_files = self.extract_files_from_frontend(jsx_content)
        
        # 写入分离的文件
        for filename, content in frontend_files.items():
            if filename.startswith('src/components/'):
                # 组件文件放在 components 目录
                file_path = frontend_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"✅ 创建组件文件: {filename}")
            elif filename in ['src/App.jsx', 'src/App.js']:
                # App 文件放在 src 目录
                with open(frontend_dir / "src" / "App.jsx", 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"✅ 创建主应用文件: App.jsx")
            elif filename.endswith('.css'):
                # CSS 文件放在 styles 目录
                css_filename = Path(filename).name
                with open(frontend_dir / "src" / "styles" / css_filename, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"✅ 创建样式文件: {css_filename}")
        
        # 如果没有分离出文件，使用原始内容创建 App.jsx
        if not frontend_files:
            logger.warning("⚠️ 未能分离组件文件，使用原始内容创建 App.jsx")
            with open(frontend_dir / "src" / "App.jsx", 'w', encoding='utf-8') as f:
                f.write(jsx_content)
        
        # 创建基础样式
        self.create_app_css(frontend_dir / "src" / "styles")
        
        # 创建 package.json
        self.create_frontend_package_json(frontend_dir)
        
        # 创建 .gitignore
        self.create_frontend_gitignore(frontend_dir)
        
        # 创建 README.md
        self.create_frontend_readme(frontend_dir)
        
        logger.info(f"✅ 前端结构创建完成: {frontend_dir}")
        return True
    
    def create_default_backend_package_json(self, backend_dir: Path):
        """创建默认的后端 package.json"""
        package_data = {
            "name": f"{self.project_name}-backend",
            "version": "1.0.0",
            "description": f"Backend API for {self.project_name}",
            "main": "app.js",
            "scripts": {
                "start": "node app.js",
                "dev": "nodemon app.js",
                "test": "jest"
            },
            "dependencies": {
                "express": "^4.18.2",
                "cors": "^2.8.5",
                "dotenv": "^16.0.3",
                "body-parser": "^1.20.2",
                "helmet": "^6.0.1",
                "morgan": "^1.10.0"
            },
            "devDependencies": {
                "nodemon": "^3.0.1",
                "jest": "^29.6.1"
            }
        }
        
        with open(backend_dir / "package.json", 'w', encoding='utf-8') as f:
            json.dump(package_data, f, indent=2)
    
    def create_default_env(self, backend_dir: Path):
        """创建默认的环境变量文件"""
        env_content = f"""PORT=5001
NODE_ENV=development
CORS_ORIGIN=http://localhost:3000

# Database (if needed)
# MONGODB_URI=mongodb://localhost:27017/{self.project_name}

# JWT (if needed)
# JWT_SECRET=your_jwt_secret_here
"""
        with open(backend_dir / ".env", 'w', encoding='utf-8') as f:
            f.write(env_content)
    
    def create_backend_gitignore(self, backend_dir: Path):
        """创建后端 .gitignore"""
        gitignore_content = """node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.env
.env.local
.env.development.local
.env.test.local
.env.production.local
dist/
build/
logs/
*.log
.DS_Store
"""
        with open(backend_dir / ".gitignore", 'w', encoding='utf-8') as f:
            f.write(gitignore_content)
    
    def create_backend_readme(self, backend_dir: Path):
        """创建后端 README.md"""
        readme_content = f"""# {self.project_name} Backend

Backend API server with debug logging enabled.

## Quick Start

```bash
# Install dependencies
npm install

# Copy environment variables
cp .env .env.local
# Edit .env.local with your configuration

# Start development server
npm run dev

# Start production server
npm start
```

## API Endpoints

The server runs on port 5001 by default.

## Features

- Express.js server
- CORS enabled
- Environment variables support
- Debug logging included
- Mock data support

## Development

```bash
# Install nodemon globally for auto-restart
npm install -g nodemon

# Start with auto-restart
npm run dev
```
"""
        with open(backend_dir / "README.md", 'w', encoding='utf-8') as f:
            f.write(readme_content)
    
    def create_index_html(self, public_dir: Path):
        """创建 index.html"""
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self.project_name}</title>
</head>
<body>
    <div id="root"></div>
</body>
</html>"""
        with open(public_dir / "index.html", 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def create_index_js(self, src_dir: Path):
        """创建 index.js"""
        js_content = """import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/App.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);"""
        with open(src_dir / "index.js", 'w', encoding='utf-8') as f:
            f.write(js_content)
    
    def create_app_css(self, styles_dir: Path):
        """创建基础样式"""
        css_content = """/* App.css */
.App {
  text-align: center;
}

.App-header {
  background-color: #282c34;
  padding: 20px;
  color: white;
}

.App-main {
  padding: 20px;
}

/* Debug logging styles */
.debug-info {
  position: fixed;
  top: 10px;
  right: 10px;
  background: rgba(0, 0, 0, 0.8);
  color: #0f0;
  padding: 10px;
  border-radius: 5px;
  font-family: monospace;
  font-size: 12px;
  max-width: 300px;
  max-height: 200px;
  overflow-y: auto;
  z-index: 9999;
}

/* Basic responsive design */
@media (max-width: 768px) {
  .App-main {
    padding: 10px;
  }
  
  .debug-info {
    font-size: 10px;
    max-width: 200px;
  }
}
"""
        with open(styles_dir / "App.css", 'w', encoding='utf-8') as f:
            f.write(css_content)
    
    def create_frontend_package_json(self, frontend_dir: Path):
        """创建前端 package.json"""
        package_data = {
            "name": f"{self.project_name}-frontend",
            "version": "1.0.0",
            "private": True,
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
                "react-scripts": "5.0.1",
                "axios": "^1.4.0",
                "react-router-dom": "^6.14.0"
            },
            "scripts": {
                "start": "react-scripts start",
                "build": "react-scripts build",
                "test": "react-scripts test",
                "eject": "react-scripts eject"
            },
            "eslintConfig": {
                "extends": ["react-app", "react-app/jest"]
            },
            "browserslist": {
                "production": [">0.2%", "not dead", "not op_mini all"],
                "development": ["last 1 chrome version", "last 1 firefox version", "last 1 safari version"]
            },
            "proxy": "http://localhost:5001"
        }
        
        with open(frontend_dir / "package.json", 'w', encoding='utf-8') as f:
            json.dump(package_data, f, indent=2)
    
    def create_frontend_gitignore(self, frontend_dir: Path):
        """创建前端 .gitignore"""
        gitignore_content = """# dependencies
/node_modules
/.pnp
.pnp.js

# testing
/coverage

# production
/build

# misc
.DS_Store
.env.local
.env.development.local
.env.test.local
.env.production.local

npm-debug.log*
yarn-debug.log*
yarn-error.log*
"""
        with open(frontend_dir / ".gitignore", 'w', encoding='utf-8') as f:
            f.write(gitignore_content)
    
    def create_frontend_readme(self, frontend_dir: Path):
        """创建前端 README.md"""
        readme_content = f"""# {self.project_name} Frontend

React frontend application with debug logging enabled.

## Quick Start

```bash
# Install dependencies
npm install

# Start development server
npm start
```

The app will open at [http://localhost:3000](http://localhost:3000).

## Features

- React 18
- Debug logging with [TRACE] markers
- API integration ready
- Responsive design
- Development proxy to backend (port 5001)

## Debug Logging

This version includes comprehensive debug logging:
- Component lifecycle events
- API interactions
- User interactions
- State changes
- Error handling

Look for `[TRACE]` messages in the browser console.

## Development

```bash
# Start development server
npm start

# Build for production
npm run build

# Run tests
npm test
```

## Backend Integration

The frontend is configured to proxy API requests to `http://localhost:5001`.
Make sure the backend server is running.
"""
        with open(frontend_dir / "README.md", 'w', encoding='utf-8') as f:
            f.write(readme_content)
    
    def create_project_root_files(self):
        """创建项目根目录文件"""
        # docker-compose.yml
        docker_compose = f"""version: '3.8'
services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - REACT_APP_API_URL=http://localhost:5001
    depends_on:
      - backend
    volumes:
      - ./frontend:/app
      - /app/node_modules

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "5001:5001"
    environment:
      - NODE_ENV=development
      - PORT=5001
    volumes:
      - ./backend:/app
      - /app/node_modules

volumes:
  node_modules:
"""
        
        with open(self.restructured_path / "docker-compose.yml", 'w') as f:
            f.write(docker_compose)
        
        # 创建启动脚本
        self.create_start_scripts()
        
        # 创建项目 README
        self.create_project_readme()
    
    def create_start_scripts(self):
        """创建启动脚本"""
        # start.sh (Unix/Linux/Mac)
        start_sh = f"""#!/bin/bash

echo "🚀 Starting {self.project_name} with debug logging..."

# Function to check if port is in use
check_port() {{
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null ; then
        echo "⚠️  Port $1 is already in use"
        return 1
    fi
    return 0
}}

# Check required ports
check_port 3000 || echo "Frontend port 3000 is busy"
check_port 5001 || echo "Backend port 5001 is busy"

# Start backend
if [ -d "backend" ]; then
    echo "📦 Starting backend server..."
    cd backend
    if [ ! -d "node_modules" ]; then
        echo "Installing backend dependencies..."
        npm install
    fi
    npm run dev &
    BACKEND_PID=$!
    echo "Backend started with PID: $BACKEND_PID"
    cd ..
else
    echo "❌ Backend directory not found"
fi

# Wait a bit for backend to start
sleep 3

# Start frontend
if [ -d "frontend" ]; then
    echo "⚛️  Starting frontend server..."
    cd frontend
    if [ ! -d "node_modules" ]; then
        echo "Installing frontend dependencies..."
        npm install
    fi
    npm start &
    FRONTEND_PID=$!
    echo "Frontend started with PID: $FRONTEND_PID"
    cd ..
else
    echo "❌ Frontend directory not found"
fi

echo ""
echo "✅ {self.project_name} is starting up!"
echo "🌐 Frontend: http://localhost:3000"
echo "🔧 Backend:  http://localhost:5001"
echo "📊 Debug logs will appear in browser console with [TRACE] prefix"
echo ""
echo "To stop servers: Ctrl+C or kill $BACKEND_PID $FRONTEND_PID"

# Wait for user input to stop
trap 'echo "Stopping servers..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit' INT
wait
"""
        
        start_script = self.restructured_path / "start.sh"
        with open(start_script, 'w') as f:
            f.write(start_sh)
        start_script.chmod(0o755)  # Make executable
        
        # start.bat (Windows)
        start_bat = f"""@echo off
echo 🚀 Starting {self.project_name} with debug logging...

REM Start backend
if exist "backend" (
    echo 📦 Starting backend server...
    cd backend
    if not exist "node_modules" (
        echo Installing backend dependencies...
        npm install
    )
    start /B cmd /C "npm run dev"
    cd ..
) else (
    echo ❌ Backend directory not found
)

timeout /t 3 /nobreak >nul

REM Start frontend
if exist "frontend" (
    echo ⚛️  Starting frontend server...
    cd frontend
    if not exist "node_modules" (
        echo Installing frontend dependencies...
        npm install
    )
    npm start
    cd ..
) else (
    echo ❌ Frontend directory not found
)

echo.
echo ✅ {self.project_name} is starting up!
echo 🌐 Frontend: http://localhost:3000
echo 🔧 Backend:  http://localhost:5001
echo 📊 Debug logs will appear in browser console with [TRACE] prefix
pause
"""
        
        with open(self.restructured_path / "start.bat", 'w') as f:
            f.write(start_bat)
    
    def create_project_readme(self):
        """创建项目 README"""
        readme_content = f"""# {self.project_name} - Debug Enabled Full-Stack App

A full-stack web application with comprehensive debug logging enabled.

## 🏗️ Project Structure

```
{self.project_name}_runnable/
├── frontend/              # React frontend with debug logs
│   ├── public/
│   ├── src/
│   │   ├── App.jsx       # Main component with [TRACE] logging
│   │   ├── index.js
│   │   └── styles/
│   ├── package.json
│   └── README.md
├── backend/               # Node.js backend API
│   ├── routes/
│   ├── controllers/
│   ├── data/
│   ├── app.js
│   ├── package.json
│   └── README.md
├── docker-compose.yml     # Docker setup
├── start.sh              # Unix/Linux/Mac startup script
├── start.bat             # Windows startup script
└── README.md             # This file
```

## 🚀 Quick Start

### Method 1: Using startup scripts (Recommended)

**On Unix/Linux/Mac:**
```bash
chmod +x start.sh
./start.sh
```

**On Windows:**
```cmd
start.bat
```

### Method 2: Manual setup

**Backend:**
```bash
cd backend
npm install
npm run dev      # Runs on port 5001
```

**Frontend:**
```bash
cd frontend
npm install
npm start        # Runs on port 3000
```

### Method 3: Using Docker

```bash
docker-compose up --build
```

## 🌐 Access Points

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:5001
- **Debug Console**: Open browser DevTools to see [TRACE] logs

## 🐛 Debug Logging Features

This project includes comprehensive debug logging:

### Frontend ([TRACE] prefix)
- Component lifecycle events
- User interactions (clicks, form submissions)
- API calls and responses
- State changes
- Error conditions
- Route changes

### Backend
- HTTP request/response logging
- API endpoint access
- Error handling
- Database operations (if applicable)

## 📊 Debug Console Usage

1. Open browser DevTools (F12)
2. Go to Console tab
3. Look for messages starting with `[TRACE]`
4. Filter by typing "TRACE" in the console filter

## 🛠️ Development

### Adding More Debug Logs

**Frontend (React):**
```javascript
console.log("[TRACE] Component action", "variable=", value);
```

**Backend (Node.js):**
```javascript
console.log("[API] Endpoint accessed", req.method, req.path);
```

### Removing Debug Logs for Production

Search for `[TRACE]` and `console.log` statements to remove or comment out.

## 📦 Dependencies

### Frontend
- React 18.2.0
- React Router DOM
- Axios for API calls

### Backend
- Express.js
- CORS
- Body Parser
- Morgan (HTTP logger)
- Helmet (Security)

## 🔧 Configuration

### Environment Variables (Backend)
Create `.env` file in backend directory:
```
PORT=5001
NODE_ENV=development
CORS_ORIGIN=http://localhost:3000
```

### API Proxy (Frontend)
Frontend is configured to proxy API requests to backend port 5001.

## 🚨 Troubleshooting

1. **Port conflicts**: Change ports in package.json scripts
2. **CORS issues**: Check CORS_ORIGIN in backend .env
3. **Module not found**: Delete node_modules and run `npm install`
4. **Debug logs not showing**: Check browser console and filter settings

## 📝 Notes

- This project was auto-generated with debug logging instrumentation
- Debug logs are optimized for development debugging
- Consider removing debug logs before production deployment
- All original functionality is preserved with added observability
"""
        
        with open(self.restructured_path / "README.md", 'w') as f:
            f.write(readme_content)
    
    def restructure_project(self) -> bool:
        """重构整个项目"""
        logger.info(f"🔄 开始重构调试项目: {self.project_name}")
        logger.info(f"原始路径: {self.project_path}")
        logger.info(f"目标路径: {self.restructured_path}")
        
        # 检查必要文件是否存在
        backend_file = self.project_path / "backend.js"
        frontend_file = self.project_path / "frontend_with_debug_logs.jsx"
        
        if not backend_file.exists():
            logger.error(f"❌ 后端文件不存在: {backend_file}")
            return False
        
        if not frontend_file.exists():
            logger.error(f"❌ 前端文件不存在: {frontend_file}")
            return False
        
        # 删除现有的重构目录
        if self.restructured_path.exists():
            shutil.rmtree(self.restructured_path)
        
        # 创建重构目录
        self.restructured_path.mkdir(parents=True, exist_ok=True)
        
        try:
            # 处理后端文件
            logger.info("📦 处理后端文件...")
            with open(backend_file, 'r', encoding='utf-8') as f:
                backend_content = f.read()
            
            backend_files = self.extract_files_from_backend(backend_content)
            if not self.create_backend_structure(backend_files):
                logger.error("❌ 后端结构创建失败")
                return False
            
            # 处理前端文件
            logger.info("⚛️  处理前端文件...")
            with open(frontend_file, 'r', encoding='utf-8') as f:
                frontend_content = f.read()
            
            # 直接使用完整的前端内容进行文件分离
            if not self.create_frontend_structure(frontend_content):
                logger.error("❌ 前端结构创建失败")
                return False
            
            # 创建项目根目录文件
            logger.info("📁 创建项目配置文件...")
            self.create_project_root_files()
            
            logger.info(f"🎉 项目重构完成!")
            logger.info(f"可运行项目位置: {self.restructured_path}")
            logger.info(f"启动命令: cd {self.restructured_path} && ./start.sh")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 重构过程中出现错误: {e}")
            return False

def restructure_all_debug_projects(debug_projects_dir: str):
    """重构所有调试项目"""
    debug_path = Path(debug_projects_dir)
    restructured_projects = []
    
    if not debug_path.exists():
        logger.error(f"❌ 调试项目目录不存在: {debug_projects_dir}")
        return
    
    logger.info(f"🔍 扫描调试项目目录: {debug_projects_dir}")
    
    # 查找所有以 "full_run_with_api_doc_" 开头的项目目录
    project_dirs = [p for p in debug_path.glob("full_run_with_api_doc_*") if p.is_dir() and not p.name.endswith('_runnable')]
    
    # 按项目名称排序
    project_dirs.sort(key=lambda x: x.name)
    
    logger.info(f"找到 {len(project_dirs)} 个可重构的调试项目")
    
    for i, project_dir in enumerate(project_dirs, 1):
        logger.info(f"\n📁 [{i}/{len(project_dirs)}] 重构项目: {project_dir.name}")
        
        # 检查是否有必要的文件
        backend_file = project_dir / "backend.js"
        frontend_file = project_dir / "frontend_with_debug_logs.jsx"
        
        if not (backend_file.exists() and frontend_file.exists()):
            logger.warning(f"⚠️ 跳过 {project_dir.name}，缺少 backend.js 或 frontend_with_debug_logs.jsx")
            continue

        restructurer = DebugProjectRestructurer(str(project_dir))
        if restructurer.restructure_project():
            restructured_projects.append(f"{project_dir.name}_runnable")
            logger.info(f"✅ 项目 {project_dir.name} 重构成功")
        else:
            logger.error(f"❌ 项目 {project_dir.name} 重构失败")
    
    return restructured_projects

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="调试项目重构工具")
    parser.add_argument("--project", help="重构单个项目路径")
    parser.add_argument("--debug_projects_dir", help="调试项目目录", 
                       default="/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/debug_logged_projects")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.project:
        # 重构单个项目
        restructurer = DebugProjectRestructurer(args.project)
        if restructurer.restructure_project():
            print("🎉 项目重构完成!")
        else:
            print("❌ 项目重构失败!")
    else:
        # 重构所有项目
        restructured = restructure_all_debug_projects(args.debug_projects_dir)
        
        logger.info(f"\n📊 重构总结:")
        logger.info(f"   成功重构项目数: {len(restructured)}")
        
        if restructured:
            logger.info("   重构的项目:")
            for project in restructured:
                logger.info(f"     - {project}")
            
            logger.info(f"\n🚀 可以使用以下命令启动项目:")
            base_dir = Path(args.debug_projects_dir)
            for project in restructured:
                project_path = base_dir / project
                logger.info(f"   cd {project_path} && ./start.sh")
        else:
            logger.info("   没有找到可重构的项目")

if __name__ == "__main__":
    main()
