#!/usr/bin/env python3
"""
批量顺序执行项目管理器
Sequential Project Batch Manager

功能：
- 按顺序启动项目
- 自动测试每个项目
- 生成测试报告
- 支持暂停/继续/跳过
- 自动端口管理
"""

import os
import sys
import time
import json
import signal
import subprocess
import requests
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

class SequentialProjectManager:
    """顺序项目管理器"""
    
    def __init__(self, projects_dir: str = "generated_websites/fullstack_projects"):
        self.projects_dir = Path(projects_dir)
        self.log_dir = Path("/tmp/sequential_logs")
        self.log_dir.mkdir(exist_ok=True)
        
        # 运行时状态
        self.current_project_index = 0
        self.running_processes = {}
        self.test_results = []
        self.interrupted = False
        
        # 配置
        self.test_timeout = 60  # 每个项目测试超时时间（秒）
        self.startup_timeout = 120  # 项目启动超时时间（秒）
        self.port_wait_time = 5  # 端口检查间隔（秒）
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 发现项目
        self.projects = self._discover_projects()
        
    def _discover_projects(self) -> List[Dict]:
        """发现所有重构后的项目"""
        projects = []
        
        if not self.projects_dir.exists():
            print(f"❌ 项目目录不存在: {self.projects_dir}")
            return projects
        
        # 查找所有重构后的项目
        for item in sorted(self.projects_dir.iterdir()):
            if item.is_dir() and item.name.endswith("_simple_project_restructured"):
                # 提取项目编号
                try:
                    project_num = int(item.name.split("_")[0])
                except:
                    project_num = 999  # 无法解析的项目放在最后
                
                # 检查项目结构
                backend_dir = item / "backend"
                frontend_dir = item / "frontend"
                
                if backend_dir.exists() and frontend_dir.exists():
                    projects.append({
                        'name': item.name,
                        'path': str(item),
                        'number': project_num,
                        'backend_port': 3000 + project_num,
                        'frontend_port': 8080 + project_num,
                        'backend_dir': str(backend_dir),
                        'frontend_dir': str(frontend_dir)
                    })
        
        # 按项目编号排序
        projects.sort(key=lambda x: x['number'])
        
        print(f"🔍 发现 {len(projects)} 个可执行项目")
        return projects
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\n🛑 收到中断信号 {signum}")
        self.interrupted = True
        self._cleanup_current_project()
        self._save_progress()
        sys.exit(0)
    
    def _cleanup_current_project(self):
        """清理当前运行的项目"""
        for service_name, process in self.running_processes.items():
            try:
                print(f"🛑 停止 {service_name}...")
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            except Exception as e:
                print(f"⚠️  停止服务异常: {e}")
        
        self.running_processes.clear()
    
    def _save_progress(self):
        """保存当前进度"""
        progress_file = self.log_dir / "progress.json"
        progress_data = {
            'current_index': self.current_project_index,
            'total_projects': len(self.projects),
            'completed_tests': len(self.test_results),
            'timestamp': datetime.now().isoformat(),
            'test_results': self.test_results
        }
        
        with open(progress_file, 'w') as f:
            json.dump(progress_data, f, indent=2)
        
        print(f"💾 进度已保存到: {progress_file}")
    
    def _load_progress(self) -> bool:
        """加载之前的进度"""
        progress_file = self.log_dir / "progress.json"
        
        if progress_file.exists():
            try:
                with open(progress_file, 'r') as f:
                    progress_data = json.load(f)
                
                self.current_project_index = progress_data.get('current_index', 0)
                self.test_results = progress_data.get('test_results', [])
                
                print(f"📂 加载上次进度: 从第 {self.current_project_index + 1} 个项目开始")
                return True
            except Exception as e:
                print(f"⚠️  加载进度失败: {e}")
        
        return False
    
    def _install_dependencies(self, project: Dict) -> bool:
        """安装项目依赖"""
        print(f"📦 安装依赖...")
        
        # 安装后端依赖
        backend_success = self._install_npm_deps(project['backend_dir'], "backend")
        
        # 安装前端依赖
        frontend_success = self._install_npm_deps(project['frontend_dir'], "frontend")
        
        return backend_success and frontend_success
    
    def _install_npm_deps(self, dir_path: str, service_name: str) -> bool:
        """安装npm依赖"""
        package_json = Path(dir_path) / "package.json"
        
        if not package_json.exists():
            print(f"⚠️  {service_name} 没有package.json文件")
            return True  # 不算失败
        
        log_file = self.log_dir / f"{service_name}_install.log"
        
        try:
            print(f"   🔧 安装 {service_name} 依赖...")
            
            # 先尝试普通安装
            result = subprocess.run(
                ["npm", "install"],
                cwd=dir_path,
                stdout=open(log_file, 'w'),
                stderr=subprocess.STDOUT,
                timeout=300
            )
            
            if result.returncode == 0:
                return True
            
            # 如果失败，尝试使用 --legacy-peer-deps
            print(f"   🔄 重试 {service_name} 依赖安装...")
            result = subprocess.run(
                ["npm", "install", "--legacy-peer-deps"],
                cwd=dir_path,
                stdout=open(log_file, 'a'),
                stderr=subprocess.STDOUT,
                timeout=300
            )
            
            return result.returncode == 0
            
        except subprocess.TimeoutExpired:
            print(f"   ❌ {service_name} 依赖安装超时")
            return False
        except Exception as e:
            print(f"   ❌ {service_name} 依赖安装失败: {e}")
            return False
    
    def _start_service(self, dir_path: str, service_name: str, port: int, env_vars: Dict = None) -> Optional[subprocess.Popen]:
        """启动服务"""
        log_file = self.log_dir / f"{service_name}.log"
        
        try:
            env = os.environ.copy()
            env['PORT'] = str(port)
            env['BROWSER'] = 'none'  # 禁止自动打开浏览器
            
            if env_vars:
                env.update(env_vars)
            
            print(f"   🚀 启动 {service_name} (端口: {port})...")
            
            process = subprocess.Popen(
                ["npm", "start"],
                cwd=dir_path,
                stdout=open(log_file, 'w'),
                stderr=subprocess.STDOUT,
                env=env
            )
            
            return process
            
        except Exception as e:
            print(f"   ❌ 启动 {service_name} 失败: {e}")
            return None
    
    def _wait_for_service(self, url: str, timeout: int = 60) -> bool:
        """等待服务启动"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, timeout=2)
                if response.status_code < 500:
                    return True
            except:
                pass
            
            time.sleep(self.port_wait_time)
            print(".", end="", flush=True)
        
        print()
        return False
    
    def _test_project(self, project: Dict) -> Dict:
        """测试项目功能"""
        test_result = {
            'project_name': project['name'],
            'project_number': project['number'],
            'backend_url': f"http://localhost:{project['backend_port']}",
            'frontend_url': f"http://localhost:{project['frontend_port']}",
            'backend_status': 'unknown',
            'frontend_status': 'unknown',
            'api_tests': [],
            'errors': [],
            'start_time': datetime.now().isoformat(),
            'end_time': None
        }
        
        try:
            # 测试后端
            print(f"   🧪 测试后端 API...")
            backend_result = self._test_backend_api(project['backend_port'])
            test_result['backend_status'] = 'success' if backend_result['success'] else 'failed'
            test_result['api_tests'] = backend_result['tests']
            
            if not backend_result['success']:
                test_result['errors'].extend(backend_result['errors'])
            
            # 测试前端
            print(f"   🌐 测试前端页面...")
            frontend_result = self._test_frontend_page(project['frontend_port'])
            test_result['frontend_status'] = 'success' if frontend_result['success'] else 'failed'
            
            if not frontend_result['success']:
                test_result['errors'].extend(frontend_result['errors'])
            
        except Exception as e:
            test_result['errors'].append(f"测试异常: {str(e)}")
        
        test_result['end_time'] = datetime.now().isoformat()
        test_result['overall_status'] = 'success' if (
            test_result['backend_status'] == 'success' and 
            test_result['frontend_status'] == 'success'
        ) else 'failed'
        
        return test_result
    
    def _test_backend_api(self, port: int) -> Dict:
        """测试后端API"""
        base_url = f"http://localhost:{port}"
        tests = []
        errors = []
        
        # 常见的API端点测试
        test_endpoints = [
            "/",
            "/api",
            "/health",
            "/status",
            "/api/orders",
            "/api/users",
            "/api/products",
            "/api/data"
        ]
        
        successful_tests = 0
        
        for endpoint in test_endpoints:
            try:
                url = f"{base_url}{endpoint}"
                response = requests.get(url, timeout=5)
                
                test_info = {
                    'endpoint': endpoint,
                    'status_code': response.status_code,
                    'success': response.status_code < 500,
                    'response_size': len(response.content)
                }
                
                tests.append(test_info)
                
                if test_info['success']:
                    successful_tests += 1
                    
            except requests.exceptions.RequestException as e:
                test_info = {
                    'endpoint': endpoint,
                    'error': str(e),
                    'success': False
                }
                tests.append(test_info)
                errors.append(f"API测试失败 {endpoint}: {e}")
        
        return {
            'success': successful_tests > 0,  # 至少有一个端点成功
            'tests': tests,
            'errors': errors,
            'successful_endpoints': successful_tests
        }
    
    def _test_frontend_page(self, port: int) -> Dict:
        """测试前端页面"""
        url = f"http://localhost:{port}"
        
        try:
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                # 检查是否包含React应用的标识
                content = response.text.lower()
                has_react_indicators = any(indicator in content for indicator in [
                    'react', 'root', 'app', 'div id="root"'
                ])
                
                return {
                    'success': True,
                    'status_code': response.status_code,
                    'content_size': len(response.content),
                    'has_react_indicators': has_react_indicators
                }
            else:
                return {
                    'success': False,
                    'status_code': response.status_code,
                    'error': f"HTTP {response.status_code}"
                }
                
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def run_sequential_tests(self, start_from: int = None, max_projects: int = None):
        """顺序执行项目测试"""
        print("🚀 开始顺序项目测试")
        print("=" * 60)
        
        # 确定开始位置
        if start_from is not None:
            self.current_project_index = max(0, start_from - 1)
        elif not self._load_progress():
            self.current_project_index = 0
        
        # 确定结束位置
        end_index = len(self.projects)
        if max_projects:
            end_index = min(self.current_project_index + max_projects, len(self.projects))
        
        print(f"📋 测试范围: 项目 {self.current_project_index + 1} 到 {end_index}")
        print(f"📊 总项目数: {len(self.projects)}")
        
        # 开始测试循环
        while self.current_project_index < end_index and not self.interrupted:
            project = self.projects[self.current_project_index]
            
            print(f"\n{'='*60}")
            print(f"🎯 测试项目 [{self.current_project_index + 1}/{len(self.projects)}]: {project['name']}")
            print(f"📁 路径: {project['path']}")
            print(f"🔗 后端端口: {project['backend_port']}")
            print(f"🌐 前端端口: {project['frontend_port']}")
            print(f"{'='*60}")
            
            success = self._test_single_project(project)
            
            if success:
                print(f"✅ 项目 {project['name']} 测试完成")
            else:
                print(f"❌ 项目 {project['name']} 测试失败")
            
            # 清理和准备下一个项目
            self._cleanup_current_project()
            time.sleep(2)  # 短暂等待，确保端口释放
            
            self.current_project_index += 1
            self._save_progress()
        
        # 生成最终报告
        self._generate_final_report()
    
    def _test_single_project(self, project: Dict) -> bool:
        """测试单个项目"""
        try:
            # 1. 安装依赖
            if not self._install_dependencies(project):
                print("❌ 依赖安装失败")
                return False
            
            # 2. 启动后端服务
            backend_process = self._start_service(
                project['backend_dir'], 
                f"{project['name']}_backend",
                project['backend_port']
            )
            
            if not backend_process:
                print("❌ 后端启动失败")
                return False
            
            self.running_processes['backend'] = backend_process
            
            # 3. 等待后端启动
            print(f"   ⏳ 等待后端启动...")
            backend_url = f"http://localhost:{project['backend_port']}"
            if not self._wait_for_service(backend_url, self.startup_timeout):
                print(f"   ❌ 后端启动超时")
                return False
            
            print(f"   ✅ 后端启动成功")
            
            # 4. 启动前端服务
            frontend_process = self._start_service(
                project['frontend_dir'],
                f"{project['name']}_frontend", 
                project['frontend_port']
            )
            
            if not frontend_process:
                print("❌ 前端启动失败")
                return False
            
            self.running_processes['frontend'] = frontend_process
            
            # 5. 等待前端启动
            print(f"   ⏳ 等待前端启动...")
            frontend_url = f"http://localhost:{project['frontend_port']}"
            if not self._wait_for_service(frontend_url, self.startup_timeout):
                print(f"   ❌ 前端启动超时")
                return False
            
            print(f"   ✅ 前端启动成功")
            
            # 6. 执行功能测试
            print(f"   🧪 执行功能测试...")
            test_result = self._test_project(project)
            self.test_results.append(test_result)
            
            # 7. 显示测试结果
            self._print_test_result(test_result)
            
            return test_result['overall_status'] == 'success'
            
        except Exception as e:
            print(f"❌ 项目测试异常: {e}")
            return False
    
    def _print_test_result(self, result: Dict):
        """打印测试结果"""
        print(f"\n📊 测试结果:")
        print(f"   🔗 后端状态: {'✅' if result['backend_status'] == 'success' else '❌'}")
        print(f"   🌐 前端状态: {'✅' if result['frontend_status'] == 'success' else '❌'}")
        
        if result['api_tests']:
            successful_apis = len([t for t in result['api_tests'] if t.get('success', False)])
            total_apis = len(result['api_tests'])
            print(f"   🧪 API测试: {successful_apis}/{total_apis} 成功")
        
        if result['errors']:
            print(f"   ⚠️  错误数量: {len(result['errors'])}")
    
    def _generate_final_report(self):
        """生成最终测试报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.log_dir / f"sequential_test_report_{timestamp}.json"
        
        # 统计结果
        total_projects = len(self.test_results)
        successful_projects = len([r for r in self.test_results if r['overall_status'] == 'success'])
        failed_projects = total_projects - successful_projects
        
        backend_success = len([r for r in self.test_results if r['backend_status'] == 'success'])
        frontend_success = len([r for r in self.test_results if r['frontend_status'] == 'success'])
        
        # 生成报告
        report = {
            'timestamp': timestamp,
            'summary': {
                'total_projects_tested': total_projects,
                'successful_projects': successful_projects,
                'failed_projects': failed_projects,
                'success_rate': (successful_projects / total_projects * 100) if total_projects > 0 else 0,
                'backend_success_rate': (backend_success / total_projects * 100) if total_projects > 0 else 0,
                'frontend_success_rate': (frontend_success / total_projects * 100) if total_projects > 0 else 0
            },
            'detailed_results': self.test_results,
            'test_configuration': {
                'startup_timeout': self.startup_timeout,
                'test_timeout': self.test_timeout,
                'port_wait_time': self.port_wait_time
            }
        }
        
        # 保存报告
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # 打印总结
        print(f"\n🎉 顺序测试完成!")
        print("=" * 60)
        print(f"📊 测试总结:")
        print(f"   📝 总项目数: {total_projects}")
        print(f"   ✅ 成功项目: {successful_projects}")
        print(f"   ❌ 失败项目: {failed_projects}")
        print(f"   📈 总成功率: {successful_projects/total_projects*100:.1f}%")
        print(f"   🔗 后端成功率: {backend_success/total_projects*100:.1f}%")
        print(f"   🌐 前端成功率: {frontend_success/total_projects*100:.1f}%")
        print(f"📄 详细报告: {report_file}")
        print("=" * 60)

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="顺序项目测试管理器")
    parser.add_argument("--start-from", type=int, help="从第N个项目开始")
    parser.add_argument("--max-projects", type=int, help="最多测试N个项目") 
    parser.add_argument("--projects-dir", default="generated_websites/fullstack_projects", 
                       help="项目目录路径")
    
    args = parser.parse_args()
    
    # 创建管理器
    manager = SequentialProjectManager(args.projects_dir)
    
    if not manager.projects:
        print("❌ 没有找到可测试的项目")
        return
    
    # 开始顺序测试
    manager.run_sequential_tests(
        start_from=args.start_from,
        max_projects=args.max_projects
    )

if __name__ == "__main__":
    main()
