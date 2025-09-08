#!/usr/bin/env python3
"""
手动运行WebVoyager测试单个debug logged项目
使用方法: python test_single_debug_project.py <project_name> [port]
例如: python test_single_debug_project.py 001_simple_project_runnable 3000
"""

import sys
import os
import json
import subprocess
import time
import signal
import requests
from dotenv import load_dotenv
from pathlib import Path

def create_single_project_tasks(project_name, port=3000, json_line=None):
    """为单个项目创建测试任务。优先用 json_line，否则从 test.jsonl 查找。"""
    base_url = f"http://localhost:{port}"
    tasks = []
    if json_line:
        try:
            data = json.loads(json_line)
            ui_instructs = data.get("ui_instruct", [])
            for idx, item in enumerate(ui_instructs):
                task = {
                    "web_name": f"Generated_Project_{project_name}",
                    "id": f"{project_name}--{idx+1}",
                    "ques": item.get("task", ""),
                    "web": base_url,
                    "expected_result": item.get("expected_result", "")
                }
                tasks.append(task)
        except Exception as e:
            print(f"解析传入的 json_line 失败: {e}")
    else:
        # 兼容老逻辑
        test_jsonl_path = Path(__file__).parent.parent / "data" / "test.jsonl"
        with open(test_jsonl_path, 'r', encoding='utf-8') as fin:
            # 从项目名提取ID: 001_simple_project_runnable -> 1
            project_id_str = project_name.split('_')[0]
            project_id = str(int(project_id_str)).zfill(6)
            for line in fin:
                try:
                    data = json.loads(line)
                    data_id = str(data.get("id", "")).zfill(6)
                    if data_id != project_id:
                        continue
                    ui_instructs = data.get("ui_instruct", [])
                    for idx, item in enumerate(ui_instructs):
                        task = {
                            "web_name": f"Generated_Project_{project_name}",
                            "id": f"{project_name}--{idx+1}",
                            "ques": item.get("task", ""),
                            "web": base_url,
                            "expected_result": item.get("expected_result", "")
                        }
                        tasks.append(task)
                    break
                except Exception as e:
                    print(f"跳过无效行: {e}")
    
    # 保存任务文件
    task_file = f"./webvoyager_task_{project_name}.jsonl"
    with open(task_file, 'w', encoding='utf-8') as f:
        for task in tasks:
            f.write(json.dumps(task, ensure_ascii=False) + '\n')
    return task_file

def check_server_health(ports, timeout=60):
    """检查一组端口是否都已被监听"""
    print(f"⏳ 等待服务器启动 (最多 {timeout} 秒)...")
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        all_ports_ready = True
        for port in ports:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    # 如果能绑定成功，说明端口未被占用
                    all_ports_ready = False
                    print(f"   端口 {port} 尚未就绪...")
                    break 
                except OSError:
                    # 如果绑定失败，说明端口已被占用（服务器已启动）
                    continue
        
        if all_ports_ready:
            print("✅ 所有服务器端口已就绪!")
            return True
        
        time.sleep(2)
    
    print(f"❌ 等待服务器启动超时 ({timeout} 秒)")
    return False

def run_webvoyager_test(task_file, project_name):
    """运行WebVoyager测试"""
    script_dir = Path(__file__).parent
    webvoyager_dir = script_dir.parent / "webvoyager"
    
    if not webvoyager_dir.exists():
        print(f"❌ WebVoyager 目录不存在: {webvoyager_dir}")
        return False
    
    print(f"🤖 运行 WebVoyager 测试: {task_file}")
    print(f"📊 结果将保存到: {webvoyager_dir}/results_debug/{project_name}")
    
    # 切换到 webvoyager 目录运行
    original_cwd = os.getcwd()
    try:
        os.chdir(webvoyager_dir)
        
        # 运行 WebVoyager 测试
        cmd = [sys.executable, "run.py", "--test_file", str(task_file), "--headless", 
               "--output_dir", f"results_debug/{project_name}"]
        print(f"执行命令: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, text=True, capture_output=True)
        
        if result.returncode == 0:
            print("✅ WebVoyager 测试完成")
            print("测试输出:")
            print(result.stdout)
            return True
        else:
            print(f"❌ WebVoyager 测试失败，返回码: {result.returncode}")
            print("错误输出:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ 运行 WebVoyager 测试出错: {e}")
        return False
    finally:
        os.chdir(original_cwd)

def main():
    if len(sys.argv) < 2:
        print("用法: python test_single_debug_project.py <project_name> [port] [--json_line 'json_data']")
        print("例如: python test_single_debug_project.py 001_simple_project_runnable 3000")
        sys.exit(1)
    
    project_name = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 3000
    backend_port = 5001  # 固定后端端口，匹配启动脚本
    
    # 解析 json_line 参数
    json_line = None
    if '--json_line' in sys.argv:
        json_idx = sys.argv.index('--json_line')
        if json_idx + 1 < len(sys.argv):
            json_line = sys.argv[json_idx + 1]
    
    # 定位项目目录
    script_dir = Path(__file__).parent
    project_dir = script_dir / "debug_logged_projects" / project_name
    
    if not project_dir.exists():
        print(f"❌ 项目目录不存在: {project_dir}")
        sys.exit(1)
    
    print(f"🚀 测试项目: {project_name}")
    print(f"📁 项目路径: {project_dir}")
    print(f"🌐 前端端口: {port}")
    print(f"🔗 后端端口: {backend_port}")
    
    # 创建测试任务
    print("📝 创建测试任务...")
    task_file = create_single_project_tasks(project_name, port, json_line)
    if not Path(task_file).exists():
        print(f"❌ 测试任务文件创建失败: {task_file}")
        sys.exit(1)
    print(f"✅ 测试任务已创建: {task_file}")
    
    # 启动项目
    print("🚀 启动项目...")
    original_cwd = os.getcwd()
    frontend_process = None
    backend_process = None
    
    try:
        # 启动前端
        frontend_path = project_dir / "frontend"
        if frontend_path.exists():
            print(f"⚛️ 启动前端服务器...")
            os.chdir(frontend_path)
            
            # 安装前端依赖
            print("安装前端依赖...")
            install_result = subprocess.run(['npm', 'install'], capture_output=True, text=True, timeout=300)
            if install_result.returncode != 0:
                print("❌ 前端 npm install 失败:")
                print(install_result.stderr)
                return 1
            
            # 启动前端服务器
            print("启动前端服务器...")
            env = os.environ.copy()
            env['PORT'] = str(port)
            frontend_process = subprocess.Popen(
                ['npm', 'start'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                preexec_fn=os.setsid
            )
            print(f"前端服务器进程PID: {frontend_process.pid}")
        else:
            print(f"❌ 前端目录不存在: {frontend_path}")
            return 1
        
        # 启动后端
        backend_path = project_dir / "backend"
        if backend_path.exists():
            print(f"📦 启动后端服务器...")
            os.chdir(backend_path)
            
            # 安装后端依赖
            print("安装后端依赖...")
            install_result = subprocess.run(['npm', 'install'], capture_output=True, text=True, timeout=300)
            if install_result.returncode != 0:
                print("❌ 后端 npm install 失败:")
                print(install_result.stderr)
                return 1
            
            # 启动后端服务器
            print("启动后端服务器...")
            backend_process = subprocess.Popen(
                ['npm', 'start'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid
            )
            print(f"后端服务器进程PID: {backend_process.pid}")
        else:
            print(f"❌ 后端目录不存在: {backend_path}")
            return 1
        
        # 等待服务器启动
        if check_server_health([port, backend_port]):
            # 运行测试
            os.chdir(original_cwd)
            test_success = run_webvoyager_test(Path(task_file).absolute(), project_name)
            
            if test_success:
                print(f"🎉 项目 {project_name} 测试成功!")
                return_code = 0
            else:
                print(f"❌ 项目 {project_name} 测试失败!")
                return_code = 1
        else:
            print(f"❌ 项目 {project_name} 服务器启动失败!")
            return_code = 1
        
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断测试")
        return_code = 1
    except Exception as e:
        print(f"❌ 测试过程出错: {e}")
        return_code = 1
    finally:
        # 清理
        print("🛑 停止服务器进程...")
        if frontend_process:
            try:
                os.killpg(os.getpgid(frontend_process.pid), signal.SIGTERM)
                time.sleep(2)
            except:
                pass
        
        if backend_process:
            try:
                os.killpg(os.getpgid(backend_process.pid), signal.SIGTERM)
                time.sleep(2)
            except:
                pass
                
        os.chdir(original_cwd)
        
        # 清理任务文件
        try:
            Path(task_file).unlink()
            print(f"🗑️ 已清理任务文件: {task_file}")
        except:
            pass
    
    sys.exit(return_code)

if __name__ == "__main__":
    main()
