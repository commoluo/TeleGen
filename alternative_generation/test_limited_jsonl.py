#!/usr/bin/env python3
"""
使用data/test.jsonl文件测试生成的项目 - 改进版本
- 限制同时运行的任务数量
- 增加任务间延迟
- 避免OpenAI API速率限制
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

def create_limited_webvoyager_tasks(jsonl_file, project_name, port=3000, max_tasks=5):
    """从jsonl文件创建限量的WebVoyager测试任务"""
    base_url = f"http://localhost:{port}"
    
    # 读取jsonl文件
    with open(jsonl_file, 'r', encoding='utf-8') as f:
        test_cases = [json.loads(line.strip()) for line in f if line.strip()]
    
    tasks = []
    task_count = 0
    
    # 只取前几个测试用例，每个用例只取前几个任务
    for i, test_case in enumerate(test_cases[:2]):  # 只取前2个测试用例
        if task_count >= max_tasks:
            break
            
        test_id = test_case.get('id', f'test_{i:03d}')
        instruction = test_case.get('instruction', 'No instruction provided')
        ui_instructions = test_case.get('ui_instruct', [])
        
        # 为每个UI指令创建一个任务，但限制数量
        for j, ui_task in enumerate(ui_instructions[:3]):  # 每个用例最多3个任务
            if task_count >= max_tasks:
                break
                
            task = {
                "web_name": f"Generated_Project_{project_name}",
                "id": f"{project_name}--{test_id}--task_{j:02d}",
                "ques": ui_task.get('task', 'No task description'),
                "web": base_url,
                "expected_result": ui_task.get('expected_result', 'No expected result specified')
            }
            tasks.append(task)
            task_count += 1
    
    print(f"📋 已创建 {len(tasks)} 个测试任务 (限制: {max_tasks})")
    
    # 保存任务文件
    task_file = f"./webvoyager_task_{project_name}_limited.jsonl"
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
                    # 如果绑定失败，说明端口已被占用
                    print(f"   ✅ 端口 {port} 已被监听。")
                    pass
        
        if all_ports_ready:
            print(f"✅ 所有指定端口 {ports} 都已成功启动!")
            return True
            
        time.sleep(2) # 每2秒检查一次

    print(f"❌ 服务器在 {timeout} 秒内部分或全部端口未成功启动: {ports}")
    return False

def run_limited_webvoyager_test(jsonl_file, project_name, port=3000, max_tasks=5):
    """运行限量的WebVoyager测试"""
    
    print(f"--- 步骤 1: 加载环境变量 ---")
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        print(f"❌ 错误: .env 文件未找到于 {env_path}")
        return False
    load_dotenv(dotenv_path=env_path)
    
    print("✅ .env环境变量已加载，API Key将由WebVoyager自动读取。")
    
    # 从 .env 或使用默认值获取配置
    script_dir = Path(__file__).parent
    projects_dir = os.getenv("PROJECTS_DIR", str(script_dir / "generated_websites" / "fullstack_projects"))
    webvoyager_dir = os.getenv("WEBVOYAGER_DIR", str(script_dir.parent / "webvoyager"))
    results_dir = os.getenv("RESULTS_DIR", str(script_dir / "webvoyager_results"))
    
    project_path = Path(projects_dir) / project_name
    
    if not project_path.exists():
        print(f"❌ 错误: 项目不存在: {project_path}")
        return False
    
    frontend_path = project_path / "frontend"
    backend_path = project_path / "backend"
    
    print(f"\\n--- 步骤 2: 启动项目服务器 ({project_name}) ---")
    
    server_process = None
    backend_process = None
    original_cwd = Path.cwd()

    try:
        # 启动前端
        if frontend_path.exists():
            print(f"进入前端目录: {frontend_path}")
            os.chdir(frontend_path)
            if not (frontend_path / "node_modules").exists():
                print("执行命令: npm install (frontend)")
                install_process = subprocess.run(['npm', 'install'], capture_output=True, text=True, timeout=300)
                if install_process.returncode != 0:
                    print("❌ 前端 npm install 失败:")
                    print(install_process.stderr)
                    return False
            
            print("执行命令: npm start (frontend)")
            # 设置React开发服务器端口
            env = os.environ.copy()
            env['PORT'] = str(port)
            server_process = subprocess.Popen(
                ['npm', 'start'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                preexec_fn=os.setsid
            )
            print(f"前端服务器进程PID: {server_process.pid}")
        
        # 启动后端
        if backend_path.exists():
            print(f"进入后端目录: {backend_path}")
            os.chdir(backend_path)
            if not (backend_path / "node_modules").exists():
                print("执行命令: npm install (backend)")
                install_process = subprocess.run(['npm', 'install'], capture_output=True, text=True, timeout=300)
                if install_process.returncode != 0:
                    print("❌ 后端 npm install 失败:")
                    print(install_process.stderr)
                    return False

            print("执行命令: npm start (backend)")
            backend_process = subprocess.Popen(
                ['npm', 'start'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid
            )
            print(f"后端服务器进程PID: {backend_process.pid}")

        # 创建限量测试任务
        os.chdir(script_dir)
        task_file = create_limited_webvoyager_tasks(jsonl_file, project_name, port, max_tasks)
        
        # 健康检查
        print(f"\\n--- 步骤 3: 健康检查 ---")
        ports_to_check = [port] # 默认检查前端端口
        if backend_path.exists():
            # 从环境变量读取后端端口，默认为5001
            backend_port = int(os.getenv("BACKEND_PORT", "5001"))
            ports_to_check.append(backend_port) 
        
        if not check_server_health(ports_to_check):
            print("❌ 服务器启动失败")
            return False
        
        # 运行WebVoyager测试
        print(f"\\n--- 步骤 4: 运行 WebVoyager 测试 (限量版) ---")
        # 将输出目录和任务文件路径构造成绝对路径
        task_file_abs = Path(__file__).parent / task_file
        output_dir_abs = Path(results_dir) / f"{project_name}_limited_test"
        
        # 切换到webvoyager目录
        os.chdir(Path(webvoyager_dir))
        
        # 运行WebVoyager with更保守的参数
        webvoyager_cmd = [
            'python', 'run.py',
            '--test_file', str(task_file_abs),
            '--headless',
            '--max_iter', '5',  # 降低最大迭代次数
            '--max_attached_imgs', '2',  # 减少附加图片数量
            '--temperature', '0.5',  # 降低温度
            '--output_dir', str(output_dir_abs),
            '--window_width', '1024',
            '--window_height', '768'
        ]
        
        print(f"执行命令: {' '.join(webvoyager_cmd)}")
        print("⏳ 开始测试，请耐心等待...")
        
        # 运行WebVoyager
        result = subprocess.run(webvoyager_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ WebVoyager测试完成")
            print(f"📊 结果保存在: {output_dir_abs}")
            
            # 显示结果摘要
            if output_dir_abs.exists():
                task_dirs = [d for d in output_dir_abs.iterdir() if d.is_dir()]
                print(f"📈 测试摘要: 共完成 {len(task_dirs)} 个任务")
        else:
            print("❌ WebVoyager测试失败")
            print("--- WebVoyager STDOUT ---")
            print(result.stdout)
            print("--- WebVoyager STDERR ---")
            print(result.stderr)
        
        return result.returncode == 0
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        return False
        
    finally:
        print(f"\\n--- 步骤 5: 清理和关闭 ---")
        # 清理：关闭服务器
        if server_process:
            try:
                print(f"关闭前端服务器进程 {server_process.pid}...")
                os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
                time.sleep(2)
            except ProcessLookupError:
                print(f"前端服务器进程 {server_process.pid} 已不存在。")
            except Exception as e:
                print(f"关闭前端服务器时出错: {e}")

        if backend_process:
            try:
                print(f"关闭后端服务器进程 {backend_process.pid}...")
                os.killpg(os.getpgid(backend_process.pid), signal.SIGTERM)
                time.sleep(2)
            except ProcessLookupError:
                print(f"后端服务器进程 {backend_process.pid} 已不存在。")
            except Exception as e:
                print(f"关闭后端服务器时出错: {e}")
        
        # 清理任务文件
        os.chdir(original_cwd)
        try:
            task_file_path = Path(__file__).parent / task_file
            if task_file_path.exists():
                os.remove(task_file_path)
                print(f"✅ 已清理临时任务文件: {task_file_path}")
        except Exception as e:
            print(f"清理任务文件时出错: {e}")

def main():
    if len(sys.argv) < 2:
        print("使用方法: python test_limited_jsonl.py <project_name> [port] [max_tasks]")
        print("例如: python test_limited_jsonl.py 001_simple_project_restructured 3000 5")
        print("\\n该脚本会使用../data/test.jsonl文件中的前几个测试任务")
        print("max_tasks: 限制测试任务数量，避免API速率限制 (默认: 5)")
        
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
        
        script_dir = Path(__file__).parent
        projects_dir = os.getenv("PROJECTS_DIR", str(script_dir / "generated_websites" / "fullstack_projects"))
        try:
            if not Path(projects_dir).exists():
                print(f"  (项目目录不存在: {projects_dir})")
                return

            projects = [d for d in os.listdir(projects_dir) if d.endswith('_restructured')]
            for project in sorted(projects)[:10]:  # 显示前10个
                print(f"  - {project}")
            if len(projects) > 10:
                print(f"  ... 还有 {len(projects) - 10} 个项目")
        except:
            print("  (无法列出项目)")
        
        return
    
    project_name = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    max_tasks = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    
    # 使用相对路径找到test.jsonl文件
    jsonl_file = Path(__file__).parent.parent / "data" / "test.jsonl"
    
    if not jsonl_file.exists():
        print(f"❌ 错误: 测试文件不存在: {jsonl_file}")
        return
    
    print(f"📋 使用测试文件: {jsonl_file}")
    print(f"🎯 项目: {project_name}")
    print(f"🚀 端口: {port}")
    print(f"📊 最大任务数: {max_tasks}")
    
    success = run_limited_webvoyager_test(jsonl_file, project_name, port, max_tasks)
    
    if success:
        print("\\n🎉 限量测试成功完成!")
    else:
        print("\\n💥 测试失败!")
        sys.exit(1)

if __name__ == "__main__":
    main()
