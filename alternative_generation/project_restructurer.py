"""
项目重构脚本
将生成的全栈项目代码重构为可运行的项目结构
"""
import os
import re
import json
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional

class ProjectRestructurer:
    """项目重构器 - 将生成的代码转换为可运行的项目结构"""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.project_name = self.project_path.name
        self.restructured_path = self.project_path.parent / f"{self.project_name}_restructured"
        self.is_organized_project = False  # 标记是否为organized_optimized_code中的项目
        
    def clean_code_content(self, content: str) -> str:
        """清理代码内容，移除markdown标记和多余的格式"""
        # 移除开头的多重代码块标记（如 ````javascript）
        content = re.sub(r'^````[\w\s]*\n', '', content, flags=re.MULTILINE)
        content = re.sub(r'^```[\w\s]*\n', '', content, flags=re.MULTILINE)
        
        # 移除结尾的代码块标记
        content = re.sub(r'\n````$', '', content, flags=re.MULTILINE)
        content = re.sub(r'\n```$', '', content, flags=re.MULTILINE)
        
        # 移除plaintext标记
        content = re.sub(r'^```plaintext\n', '', content, flags=re.MULTILINE)
        
        # 移除文件路径注释
        content = re.sub(r'^// filepath:.*?\n', '', content, flags=re.MULTILINE)
        
        # 移除文件结构注释块
        content = re.sub(r'^//.*目录结构.*?\n(//.*\n)*', '', content, flags=re.MULTILINE | re.DOTALL)
        
        # 移除项目结构说明
        content = re.sub(r'^[a-zA-Z_-]+/\n(├──.*\n|│.*\n|└──.*\n)*', '', content, flags=re.MULTILINE)
        
        return content.strip()
    
    def extract_files_from_content(self, content: str) -> Dict[str, str]:
        """从内容中提取单独的文件"""
        files = {}
        
        # 首先尝试 // FILE: filename 格式（这是实际使用的格式）
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
                print(f"📄 提取文件: {filename} ({len(file_content)} 字符)")
        
        # 如果没有找到，尝试原来的 // filename 格式（兼容旧格式）
        if not files:
            pattern = r'^// ([^/\n]+\.(js|jsx|json|env|yml|yaml|md))\s*\n(.*?)(?=\n// [^/\n]+\.|$)'
            matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
            
            for match in matches:
                filename = match.group(1).strip()
                file_content = match.group(3).strip()
                
                # 清理内容：移除代码块标记
                file_content = re.sub(r'^```\w*\n', '', file_content, flags=re.MULTILINE)
                file_content = re.sub(r'\n```$', '', file_content, flags=re.MULTILINE)
                
                if file_content.strip():
                    files[filename] = file_content.strip()
                    print(f"📄 提取文件: {filename} ({len(file_content)} 字符)")
        
        # 如果没有找到，尝试 **filename** 格式
        if not files:
            pattern = r'\*\*([^*]+\.(jsx?|tsx?|css|html|json|py|yml|yaml|md))\*\*\s*\n(.*?)(?=\n\*\*[^*]+\.(jsx?|tsx?|css|html|json|py|yml|yaml|md)\*\*|$)'
            matches = re.finditer(pattern, content, re.DOTALL)
            
            for match in matches:
                filename = match.group(1).strip()
                file_content = match.group(3).strip()
                
                # 清理内容：移除代码块标记
                file_content = re.sub(r'^```\w*\n', '', file_content, flags=re.MULTILINE)
                file_content = re.sub(r'\n```$', '', file_content, flags=re.MULTILINE)
                
                if file_content.strip():
                    files[filename] = file_content.strip()
                    print(f"📄 提取文件: {filename} ({len(file_content)} 字符)")
        
        # 如果没有找到文件分隔，尝试按语言类型分割
        if not files:
            print("⚠️  未找到标准文件格式，尝试其他格式...")
            # JavaScript/Node.js 代码
            js_matches = re.finditer(r'```javascript\n(.*?)```', content, re.DOTALL)
            for i, match in enumerate(js_matches):
                files[f'code_{i}.js'] = match.group(1).strip()
            
            # JSX 代码
            jsx_matches = re.finditer(r'```jsx\n(.*?)```', content, re.DOTALL)
            for i, match in enumerate(jsx_matches):
                files[f'component_{i}.jsx'] = match.group(1).strip()
            
            # CSS 代码
            css_matches = re.finditer(r'```css\n(.*?)```', content, re.DOTALL)
            for i, match in enumerate(css_matches):
                files[f'style_{i}.css'] = match.group(1).strip()
        
        return files
    
    def create_standard_project_structure(self, component_type: str, tech_stack: str) -> Dict[str, str]:
        """创建标准项目结构模板"""
        structures = {}
        
        if component_type == "frontend":
            if "React" in tech_stack:
                structures = {
                    "public/index.html": self.get_react_index_html(),
                    "src/index.js": self.get_react_index_js(),
                    "src/App.jsx": "",  # 将从生成的代码中提取
                    "src/components/.gitkeep": "",
                    "src/styles/App.css": "",
                    "package.json": self.get_react_package_json(),
                    ".gitignore": self.get_react_gitignore(),
                    "README.md": f"# {self.project_name} Frontend\n\nReact application"
                }
        
        elif component_type == "backend":
            if "Node" in tech_stack:
                structures = {
                    "app.js": "",  # 将从生成的代码中提取
                    "package.json": self.get_node_package_json(),
                    "routes/.gitkeep": "",
                    "controllers/.gitkeep": "",
                    "models/.gitkeep": "",
                    "middleware/.gitkeep": "",
                    "config/.gitkeep": "",
                    ".env.example": self.get_env_example(),
                    ".gitignore": self.get_node_gitignore(),
                    "README.md": f"# {self.project_name} Backend\n\nNode.js application"
                }
        
        return structures
    
    def get_react_index_html(self) -> str:
        """获取React index.html模板"""
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_name}</title>
</head>
<body>
    <div id="root"></div>
</body>
</html>'''.format(project_name=self.project_name)
    
    def get_react_index_js(self) -> str:
        """获取React index.js模板"""
        return '''import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/App.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);'''
    
    def get_react_package_json(self) -> str:
        """获取React package.json模板"""
        return json.dumps({
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
            }
        }, indent=2)
    
    def get_node_package_json(self) -> str:
        """获取Node.js package.json模板"""
        return json.dumps({
            "name": f"{self.project_name}-backend",
            "version": "1.0.0",
            "description": f"Backend for {self.project_name}",
            "main": "app.js",
            "scripts": {
                "start": "node app.js",
                "dev": "nodemon app.js",
                "test": "jest"
            },
            "dependencies": {
                "express": "^4.18.2",
                "mongoose": "^7.4.0",
                "cors": "^2.8.5",
                "dotenv": "^16.3.1",
                "bcryptjs": "^2.4.3",
                "jsonwebtoken": "^9.0.1",
                "joi": "^17.9.2"
            },
            "devDependencies": {
                "nodemon": "^3.0.1",
                "jest": "^29.6.1"
            }
        }, indent=2)
    
    def get_react_gitignore(self) -> str:
        """获取React .gitignore"""
        return '''# dependencies
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
yarn-error.log*'''
    
    def get_node_gitignore(self) -> str:
        """获取Node.js .gitignore"""
        return '''node_modules/
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
*.log'''
    
    def get_env_example(self) -> str:
        """获取环境变量示例"""
        return '''PORT=3000
NODE_ENV=development
MONGODB_URI=mongodb://localhost:27017/{project_name}
JWT_SECRET=your_jwt_secret_here
CORS_ORIGIN=http://localhost:3000'''.format(project_name=self.project_name)
    
    def restructure_component(self, component_type: str, tech_stack: str) -> bool:
        """重构单个组件"""
        
        # 根据组件类型确定文件扩展名
        if component_type == "frontend":
            component_file = self.project_path / f"{component_type}.jsx"
        elif component_type == "deployment":
            component_file = self.project_path / f"{component_type}.yml"
        else:
            component_file = self.project_path / f"{component_type}.js"
        
        if not component_file.exists():
            print(f"⚠️  {component_type} 文件不存在: {component_file}")
            return False
        
        # 读取原始内容
        with open(component_file, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        
        # 清理内容
        cleaned_content = self.clean_code_content(raw_content)
        
        # 提取文件
        files = self.extract_files_from_content(cleaned_content)
        
        # 创建组件目录
        component_dir = self.restructured_path / component_type
        component_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建标准结构
        standard_structure = self.create_standard_project_structure(component_type, tech_stack)
        
        # 写入标准结构文件
        for file_path, content in standard_structure.items():
            full_path = component_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        # 写入提取的文件
        for filename, content in files.items():
            # 根据文件类型和组件类型确定存放位置
            if component_type == "backend":
                # Backend 文件的特殊处理
                if filename == 'package.json':
                    file_path = component_dir / filename
                elif filename == '.env':
                    file_path = component_dir / filename
                elif filename == 'app.js':
                    file_path = component_dir / filename
                elif filename.startswith('models/'):
                    file_path = component_dir / filename
                elif filename.startswith('routes/'):
                    file_path = component_dir / filename
                elif filename.startswith('controllers/'):
                    file_path = component_dir / filename
                elif filename.startswith('middleware/'):
                    file_path = component_dir / filename
                elif 'model' in filename.lower() or filename.endswith('Model.js'):
                    file_path = component_dir / "models" / Path(filename).name
                elif 'route' in filename.lower() or filename.endswith('Routes.js'):
                    file_path = component_dir / "routes" / Path(filename).name
                elif 'controller' in filename.lower() or filename.endswith('Controller.js'):
                    file_path = component_dir / "controllers" / Path(filename).name
                elif 'middleware' in filename.lower():
                    file_path = component_dir / "middleware" / Path(filename).name
                else:
                    file_path = component_dir / filename
            elif component_type == "frontend":
                # Frontend 文件的处理
                if filename.endswith('.jsx') or filename.endswith('.js'):
                    if 'component' in filename.lower() or filename.startswith('src/components/'):
                        file_path = component_dir / "src" / "components" / Path(filename).name
                    elif filename in ['App.jsx', 'App.js']:
                        file_path = component_dir / "src" / filename
                    elif filename.startswith('src/'):
                        file_path = component_dir / filename
                    else:
                        file_path = component_dir / filename
                elif filename.endswith('.css'):
                    file_path = component_dir / "src" / "styles" / Path(filename).name
                elif filename.endswith('.html'):
                    file_path = component_dir / "public" / Path(filename).name
                else:
                    file_path = component_dir / filename
            elif component_type == "database":
                # Database 文件的处理
                if filename.endswith('.sql'):
                    file_path = component_dir / "migrations" / Path(filename).name
                elif filename.endswith('.js') and 'seed' in filename.lower():
                    file_path = component_dir / "seeds" / Path(filename).name
                else:
                    file_path = component_dir / filename
            elif component_type == "deployment":
                # Deployment 文件的处理
                file_path = component_dir / filename
            else:
                file_path = component_dir / filename
            
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ 创建文件: {file_path}")
        
        return True
    
    def restructure_project(self):
        """重构项目的主要流程"""
        print(f"🔄 开始重构项目: {self.project_name}")
        print(f"原始路径: {self.project_path}")
        print(f"目标路径: {self.restructured_path}")

        if self.restructured_path.exists():
            print("🗑️  删除已存在的重构目录...")
            shutil.rmtree(self.restructured_path)
        
        self.restructured_path.mkdir(parents=True, exist_ok=True)

        try:
            # 检查是否是优化后的项目
            is_optimized_project = '_runnable_optimized' in self.project_path.name

            if is_optimized_project:
                # =================================================
                # 新增：处理 optimized_code 中的项目
                # =================================================
                print("🔍 检测到优化项目，使用特定逻辑...")
                
                # 1. 查找前端JSX文件
                frontend_file_name = f"{self.project_name}.jsx"
                frontend_file_path = self.project_path / frontend_file_name
                
                if not frontend_file_path.exists():
                    print(f"❌ 优化的前端文件未找到: {frontend_file_path}")
                    return False
                
                frontend_content = frontend_file_path.read_text(encoding='utf-8')
                print(f"📄 读取前端文件: {frontend_file_path.name}")

                # 2. 查找后端JS文件
                backend_file_path = self.project_path / "backend.js"
                backend_content = ""
                if backend_file_path.exists():
                    backend_content = backend_file_path.read_text(encoding='utf-8')
                    print(f"📄 读取后端文件: {backend_file_path.name}")
                else:
                    print("⚠️  未找到 backend.js 文件，将只处理前端。")

                # 3. 创建项目结构
                self.create_project_files_from_contents(frontend_content, backend_content)

            else:
                # =================================================
                # 原始逻辑：处理 debug_logged_projects 中的项目
                # =================================================
                print("🔍 使用原始项目逻辑...")
                frontend_file = self.project_path / "frontend_original.jsx"
                backend_file = self.project_path / "backend.js"

                if not frontend_file.exists():
                    print(f"❌ 前端文件不存在: {frontend_file}")
                    return False

                frontend_content = frontend_file.read_text(encoding='utf-8')
                backend_content = backend_file.read_text(encoding='utf-8') if backend_file.exists() else ""
                
                self.create_project_files_from_contents(frontend_content, backend_content)

            print("\n🎉 项目重构完成!")
            print(f"重构后的项目位置: {self.restructured_path}")
            return True

        except Exception as e:
            print(f"❌ 重构过程中发生异常: {e}")
            import traceback
            traceback.print_exc()
            return False

    def create_project_files_from_contents(self, frontend_content: str, backend_content: str):
        """根据前后端内容创建文件"""
        # 创建前端
        frontend_dir = self.restructured_path / "frontend"
        frontend_dir.mkdir(exist_ok=True)
        self.setup_frontend(frontend_dir, frontend_content)

        # 创建后端
        if backend_content:
            backend_dir = self.restructured_path / "backend"
            backend_dir.mkdir(exist_ok=True)
            self.setup_backend(backend_dir, backend_content)
        
        # 创建顶层文件
        self.create_top_level_files()
    
    def setup_frontend(self, frontend_dir: Path, content: str):
        """设置前端文件"""
        # 解析并提取前端文件
        files = self.extract_files_from_content(content)
        
        # 写入提取的前端文件
        for filename, file_content in files.items():
            file_path = frontend_dir / filename
            
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)
            
            print(f"✅ 创建前端文件: {file_path}")
    
    def setup_backend(self, backend_dir: Path, content: str):
        """设置后端文件"""
        # 解析并提取后端文件
        files = self.extract_files_from_content(content)
        
        # 写入提取的后端文件
        for filename, file_content in files.items():
            file_path = backend_dir / filename
            
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)
            
            print(f"✅ 创建后端文件: {file_path}")
    
    def create_top_level_files(self):
        """创建顶层文件"""
        # 创建 README.md
        readme_content = f"# {self.project_name}\n\n重构后的全栈项目"
        with open(self.restructured_path / "README.md", 'w', encoding='utf-8') as f:
            f.write(readme_content)
        
        print("✅ 创建顶层文件: README.md")
    
    def restructure_organized_project(self) -> bool:
        """重构organized_optimized_code中的项目"""
        print(f"📁 处理organized项目结构...")
        
        # 查找项目文件
        jsx_files = list(self.project_path.glob("*_optimized.jsx"))
        backend_files = list(self.project_path.glob("backend.js"))
        
        if not jsx_files:
            print(f"❌ 未找到优化的JSX文件")
            return False
        
        if not backend_files:
            print(f"❌ 未找到backend.js文件")
            return False
        
        jsx_file = jsx_files[0]
        backend_file = backend_files[0]
        
        print(f"📄 JSX文件: {jsx_file.name}")
        print(f"📄 Backend文件: {backend_file.name}")
        
        # 读取JSX文件内容
        with open(jsx_file, 'r', encoding='utf-8') as f:
            jsx_content = f.read()
        
        # 读取backend文件内容
        with open(backend_file, 'r', encoding='utf-8') as f:
            backend_content = f.read()
        
        # 解析JSX文件中的多文件结构
        files = self.extract_files_from_content(jsx_content)
        
        # 如果没有解析到文件，直接使用JSX内容创建前端
        if not files:
            print("📄 JSX文件未包含多文件结构，使用单文件模式")
            files = {
                'src/App.jsx': jsx_content,
                'package.json': self.create_default_package_json(),
                'public/index.html': self.create_default_index_html()
            }
        
        # 创建前端目录结构
        frontend_dir = self.restructured_path / "frontend"
        frontend_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建后端目录结构（提前创建以便后续使用）
        backend_dir = self.restructured_path / "backend"
        backend_dir.mkdir(parents=True, exist_ok=True)
        
        # 写入前端文件
        for file_path, content in files.items():
            full_path = frontend_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(self.clean_code_content(content))
            
            print(f"✅ 创建前端文件: {file_path}")
        
        # 复制原始项目中的重要配置文件（如.gitignore等）
        self.copy_original_config_files(frontend_dir, backend_dir)
        
        # 解析backend文件中的多文件结构
        backend_files = self.extract_files_from_content(backend_content)
        
        if backend_files:
            # 如果backend.js包含多文件结构，解析并创建对应文件
            for file_path, content in backend_files.items():
                full_path = backend_dir / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(self.clean_code_content(content))
                
                print(f"✅ 创建后端文件: {file_path}")
        else:
            # 如果没有解析到文件，直接使用backend内容创建server.js
            backend_main_file = backend_dir / "server.js"
            with open(backend_main_file, 'w', encoding='utf-8') as f:
                f.write(self.clean_code_content(backend_content))
            
            print(f"✅ 创建后端文件: server.js")
            
            # 创建后端package.json
            backend_package_json = {
                "name": f"{self.project_name}-backend",
                "version": "1.0.0",
                "description": "Backend for " + self.project_name,
                "main": "server.js",
                "scripts": {
                    "start": "node server.js",
                    "dev": "nodemon server.js"
                },
                "dependencies": {
                    "express": "^4.18.0",
                    "cors": "^2.8.5",
                    "body-parser": "^1.20.0"
                },
                "devDependencies": {
                    "nodemon": "^2.0.20"
                }
            }
            
            with open(backend_dir / "package.json", 'w', encoding='utf-8') as f:
                json.dump(backend_package_json, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 创建后端配置: package.json")
        
        # 创建项目根目录的启动脚本
        self.create_organized_project_scripts()
        
        print(f"🎉 Organized项目重构完成!")
        return True
    
    def create_organized_project_scripts(self):
        """为organized项目创建启动脚本"""
        # 检查后端主文件名
        backend_dir = self.restructured_path / "backend"
        main_file = "app.js" if (backend_dir / "app.js").exists() else "server.js"
        
        # 创建启动脚本
        start_script = f"""#!/bin/bash
# 启动{self.project_name}项目

echo "🚀 启动{self.project_name}项目..."

# 启动后端
echo "📡 启动后端服务器..."
cd backend
npm install
npm start &
BACKEND_PID=$!

# 等待后端启动
sleep 3

# 启动前端
echo "🌐 启动前端应用..."
cd ../frontend
npm install
npm start &
FRONTEND_PID=$!

echo "✅ 项目启动完成!"
echo "后端地址: http://localhost:3001"
echo "前端地址: http://localhost:3000"
echo ""
echo "按Ctrl+C停止服务..."

# 等待用户停止
wait

# 清理进程
kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
echo "🛑 项目已停止"
"""
        
        start_script_path = self.restructured_path / "start.sh"
        with open(start_script_path, 'w', encoding='utf-8') as f:
            f.write(start_script)
        
        # 设置执行权限
        os.chmod(start_script_path, 0o755)
        
        # 创建README
        readme_content = f"""# {self.project_name}

这是一个重构后的全栈项目，包含前端React应用和后端Express服务器。

## 项目结构

```
{self.project_name}_restructured/
├── frontend/          # React前端应用
│   ├── src/
│   ├── public/
│   └── package.json
├── backend/           # Express后端服务器
│   ├── server.js
│   └── package.json
├── start.sh          # 启动脚本
└── README.md         # 项目说明
```

## 快速启动

### 方法1: 使用启动脚本（推荐）
```bash
./start.sh
```

### 方法2: 手动启动

1. 启动后端：
```bash
cd backend
npm install
npm start
```

2. 启动前端：
```bash
cd frontend
npm install
npm start
```

## 访问地址

- 前端: http://localhost:3000
- 后端: http://localhost:3001

## 注意事项

- 确保已安装Node.js和npm
- 前端应用会自动代理API请求到后端服务器
- 如果端口被占用，请修改相应的配置文件
"""
        
        readme_path = self.restructured_path / "README.md"
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)
        
        print(f"✅ 创建启动脚本: start.sh")
        print(f"✅ 创建项目文档: README.md")
    
    def copy_original_config_files(self, frontend_dir, backend_dir):
        """从原始debug_logged_projects中复制重要的配置文件"""
        # 从项目名称提取项目编号 (如: 001_simple_project_runnable -> 001)
        project_number = self.project_name.split('_')[0]
        
        # 构建原始项目路径
        debug_projects_dir = self.project_path.parent.parent / "debug_logged_projects"
        
        # 首先尝试_runnable版本，然后尝试普通版本
        possible_names = [
            f"{project_number}_simple_project_runnable",
            f"{project_number}_simple_project"
        ]
        
        original_project_dir = None
        for name in possible_names:
            potential_dir = debug_projects_dir / name
            if potential_dir.exists():
                original_project_dir = potential_dir
                break
        
        if not original_project_dir:
            print(f"⚠️  未找到原始项目目录: {possible_names}")
            return
        
        print(f"📁 找到原始项目: {original_project_dir.name}")
        
        # 复制前端配置文件
        original_frontend_dir = original_project_dir / "frontend"
        if original_frontend_dir.exists():
            config_files = ['.gitignore', 'README.md']
            for config_file in config_files:
                original_file = original_frontend_dir / config_file
                if original_file.exists():
                    target_file = frontend_dir / config_file
                    # 如果目标文件不存在，则复制
                    if not target_file.exists():
                        shutil.copy2(original_file, target_file)
                        print(f"✅ 复制前端配置: {config_file}")
        
        # 复制后端配置文件
        original_backend_dir = original_project_dir / "backend"
        if original_backend_dir.exists():
            config_files = ['.gitignore', 'README.md', '.env.example']
            for config_file in config_files:
                original_file = original_backend_dir / config_file
                if original_file.exists():
                    target_file = backend_dir / config_file
                    # 如果目标文件不存在，则复制
                    if not target_file.exists():
                        shutil.copy2(original_file, target_file)
                        print(f"✅ 复制后端配置: {config_file}")
    
    def create_root_config_files(self):
        """创建项目根目录配置文件"""
        
        # docker-compose.yml
        docker_compose = '''version: '3.8'
services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - REACT_APP_API_URL=http://localhost:5000
    depends_on:
      - backend

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "5000:5000"
    environment:
      - NODE_ENV=development
      - MONGODB_URI=mongodb://mongo:27017/{project_name}
    depends_on:
      - mongo

  mongo:
    image: mongo:latest
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db

volumes:
  mongodb_data:
'''.format(project_name=self.project_name)
        
        with open(self.restructured_path / "docker-compose.yml", 'w') as f:
            f.write(docker_compose)
        
        # 项目README
        readme = f'''# {self.project_name}

This is a full-stack web application generated automatically.

## Project Structure

```
{self.project_name}_restructured/
├── frontend/          # React frontend application
├── backend/           # Node.js backend API
├── docker-compose.yml # Docker compose configuration
├── start.sh          # Quick start script
└── README.md         # This file
```

## Quick Start

### Using Docker (Recommended)
```bash
# Start all services
docker-compose up --build

# Access the application
# Frontend: http://localhost:3000
# Backend API: http://localhost:5000
# MongoDB: localhost:27017
```

### Manual Setup

#### Backend
```bash
cd backend
npm install
cp .env.example .env
# Edit .env with your configuration
npm run dev
```

#### Frontend
```bash
cd frontend
npm install
npm start
```

## Development

- Frontend runs on port 3000
- Backend API runs on port 5000
- MongoDB runs on port 27017

## Features

Generated components include all necessary functionality for a complete web application.
'''
        
        with open(self.restructured_path / "README.md", 'w') as f:
            f.write(readme)
    
    def create_start_scripts(self):
        """创建启动脚本"""
        
        # start.sh (Unix/Linux/Mac)
        start_sh = '''#!/bin/bash

echo "🚀 Starting {project_name}..."

# Check if Docker is available
if command -v docker &> /dev/null && command -v docker-compose &> /dev/null; then
    echo "📦 Using Docker..."
    docker-compose up --build
else
    echo "🔧 Using manual setup..."
    
    # Start MongoDB if available
    if command -v mongod &> /dev/null; then
        echo "Starting MongoDB..."
        mongod --fork --logpath /var/log/mongod.log
    fi
    
    # Start backend
    if [ -d "backend" ]; then
        echo "Starting backend..."
        cd backend
        npm install
        npm run dev &
        cd ..
    fi
    
    # Start frontend
    if [ -d "frontend" ]; then
        echo "Starting frontend..."
        cd frontend
        npm install
        npm start &
        cd ..
    fi
    
    echo "✅ Services started!"
    echo "Frontend: http://localhost:3000"
    echo "Backend: http://localhost:5000"
fi
'''.format(project_name=self.project_name)
        
        start_script = self.restructured_path / "start.sh"
        with open(start_script, 'w') as f:
            f.write(start_sh)
        start_script.chmod(0o755)  # Make executable
        
        # start.bat (Windows)
        start_bat = '''@echo off

echo 🚀 Starting {project_name}...

REM Check if Docker is available
docker --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo 📦 Using Docker...
    docker-compose up --build
) else (
    echo 🔧 Using manual setup...
    
    REM Start backend
    if exist "backend" (
        echo Starting backend...
        cd backend
        npm install
        start /B npm run dev
        cd ..
    )
    
    REM Start frontend
    if exist "frontend" (
        echo Starting frontend...
        cd frontend
        npm install
        npm start
        cd ..
    )
    
    echo ✅ Services started!
    echo Frontend: http://localhost:3000
    echo Backend: http://localhost:5000
)
'''.format(project_name=self.project_name)
        
        with open(self.restructured_path / "start.bat", 'w') as f:
            f.write(start_bat)

def restructure_project(project_path: str) -> bool:
    """重构单个项目"""
    restructurer = ProjectRestructurer(project_path)
    return restructurer.restructure_project()

def restructure_all_projects(projects_dir: str) -> List[str]:
    """重构所有项目"""
    projects_path = Path(projects_dir)
    restructured_projects = []
    
    if not projects_path.exists():
        print(f"❌ 项目目录不存在: {projects_dir}")
        return []
    
    print(f"🔍 扫描项目目录: {projects_dir}")
    
    # 查找所有项目目录
    for project_dir in projects_path.iterdir():
        if project_dir.is_dir() and not project_dir.name.endswith('_restructured'):
            # 检查是否有project_summary.json文件
            if (project_dir / "project_summary.json").exists():
                print(f"\n📁 发现项目: {project_dir.name}")
                
                if restructure_project(str(project_dir)):
                    restructured_projects.append(f"{project_dir.name}_restructured")
                    print(f"✅ 项目 {project_dir.name} 重构成功")
                else:
                    print(f"❌ 项目 {project_dir.name} 重构失败")
    
    return restructured_projects

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="项目重构工具")
    parser.add_argument("--project", help="重构单个项目路径")
    parser.add_argument("--projects_dir", help="重构目录下所有项目", 
                       default="generated_websites/fullstack_projects")
    
    args = parser.parse_args()
    
    if args.project:
        # 重构单个项目
        if restructure_project(args.project):
            print("🎉 项目重构完成!")
        else:
            print("❌ 项目重构失败!")
    else:
        # 重构所有项目
        restructured = restructure_all_projects(args.projects_dir)
        
        print(f"\n📊 重构总结:")
        print(f"   成功重构项目数: {len(restructured)}")
        
        if restructured:
            print("   重构的项目:")
            for project in restructured:
                print(f"     - {project}")
            
            print(f"\n🚀 可以使用以下命令启动项目:")
            for project in restructured:
                print(f"   cd {args.projects_dir}/{project} && ./start.sh")
        else:
            print("   没有找到可重构的项目")

    def create_default_package_json(self) -> str:
        """创建默认的前端package.json"""
        package_json = {
            "name": f"{self.project_name}-frontend",
            "version": "1.0.0",
            "private": True,
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
                "axios": "^1.5.0",
                "chart.js": "^4.3.0",
                "react-chartjs-2": "^5.0.0"
            },
            "scripts": {
                "start": "react-scripts start",
                "build": "react-scripts build",
                "test": "react-scripts test",
                "eject": "react-scripts eject"
            },
            "devDependencies": {
                "react-scripts": "5.0.0"
            },
            "browserslist": {
                "production": [
                    ">0.2%",
                    "not dead",
                    "not op_mini all"
                ],
                "development": [
                    "last 1 chrome version",
                    "last 1 firefox version",
                    "last 1 safari version"
                ]
            }
        }
        return json.dumps(package_json, indent=2, ensure_ascii=False)
    
    def create_default_index_html(self) -> str:
        """创建默认的index.html"""
        return f"""<!DOCTYPE html>
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
