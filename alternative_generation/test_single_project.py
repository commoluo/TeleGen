#!/usr/bin/env python3
"""
手动运行WebVoyager测试单个fullstack项目
使用方法: python test_single_project.py <project_name> [port]
例如: python test_single_project.py 001_simple_project_restructured 3000
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

# 新增：id到项目目录名的转换方法
def id_to_project_dir(project_id):
    """
    将000001_restructured等id转换为实际目录名，如001_simple_project_restructed。
    只处理数字部分和后缀。
    """
    # 只保留数字部分（遇到下划线只取前面数字）
    num = str(project_id)
    if '_' in num:
        num = num.split('_', 1)[0]
    # 去除前导零后补齐三位
    num = str(int(num)).zfill(3)
    # 补齐simple_project_restructed后缀
    return f"{num}_simple_project_restructured"

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
            project_id = str(project_name).zfill(6)
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
                    # 如果绑定失败，说明端口已被占用
                    print(f"   ✅ 端口 {port} 已被监听。")
                    pass
        
        if all_ports_ready:
            print(f"✅ 所有指定端口 {ports} 都已成功启动!")
            return True
            
        time.sleep(2) # 每2秒检查一次

    print(f"❌ 服务器在 {timeout} 秒内部分或全部端口未成功启动: {ports}")
    return False

def check_process_startup(process, name, timeout=30):
    """检查进程是否成功启动"""
    print(f"⏳ 检查{name}进程启动状态...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        poll_result = process.poll()
        if poll_result is not None:
            # 进程已退出
            stdout, stderr = process.communicate()
            print(f"❌ {name}进程意外退出，返回码: {poll_result}")
            if stdout:
                print(f"=== {name} STDOUT ===")
                print(stdout[:1000])  # 限制输出长度
            if stderr:
                print(f"=== {name} STDERR ===")
                print(stderr[:1000])  # 限制输出长度
            return False
        
        time.sleep(1)
    
    print(f"✅ {name}进程启动正常，PID: {process.pid}")
    return True

def run_webvoyager_test(project_name, port=3000, json_line=None, use_organized=False, use_debug_logged=False, use_optimized=False):
    """运行WebVoyager测试"""
    
    print(f"--- 步骤 1: 加载环境变量 ---")
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        print(f"❌ 错误: .env 文件未找到于 {env_path}")
        return False
    load_dotenv(dotenv_path=env_path)

    # 不再强制要求API key，交由webvoyager自动处理
    print("✅ .env环境变量已加载，API Key将由WebVoyager自动读取。")

    # 从 .env 或使用默认值获取配置
    script_dir = Path(__file__).parent
    
    if use_organized:
        # 使用organized_optimized_code目录
        projects_dir = script_dir / "organized_optimized_code"
        print(f"使用organized模式，项目目录: {projects_dir}")
    elif use_debug_logged:
        # 使用debug_logged_projects目录
        projects_dir = script_dir / "debug_logged_projects"
        print(f"使用debug_logged模式，项目目录: {projects_dir}")
    elif use_optimized:
        # 使用optimized_code目录
        projects_dir = script_dir / "optimized_code"
        print(f"使用optimized模式，项目目录: {projects_dir}")
    else:
        # projects_dir现在使用绝对路径，防止工作目录影响
        projects_dir = os.getenv(
            "PROJECTS_DIR",
            "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/generated_websites/fullstack_projects_20250717_174459"
        )
    
    webvoyager_dir = os.getenv("WEBVOYAGER_DIR", str(script_dir.parent / "webvoyager"))
    results_dir = os.getenv("RESULTS_DIR", str(script_dir / "webvoyager_results"))

    if use_organized or use_debug_logged or use_optimized:
        # 对于 organized, debug_logged, optimized 模式，直接使用project_name
        real_project_name = project_name
    else:
        # 新增：自动转换id为实际目录名
        real_project_name = id_to_project_dir(project_name)
    
    project_path = Path(projects_dir) / real_project_name

    if not project_path.exists():
        print(f"❌ 错误: 项目不存在: {project_path}")
        return False

    # 步骤0: 清理指定端口上的进程
    print(f"\n--- 步骤 0: 清理端口 {port} 和 5001 ---")
    ports_to_clear = [port, 5001]  # 清理前端和后端端口
    
    for port_num in ports_to_clear:
        try:
            # 查找占用端口的进程
            result = subprocess.run(['lsof', '-ti', f':{port_num}'], capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        subprocess.run(['kill', pid], check=True)
                        print(f"✅ 已终止端口 {port_num} 上的进程 PID: {pid}")
                    except subprocess.CalledProcessError:
                        print(f"⚠️  无法终止进程 PID: {pid}")
            else:
                print(f"✅ 端口 {port_num} 未被占用")
        except Exception as e:
            print(f"⚠️  清理端口 {port_num} 时出错: {e}")

    # frontend_path = project_path / "frontend"
    # backend_path = project_path / "backend"
    # print(frontend_path)
    frontend_path = Path("frontend")
    backend_path = Path("backend")
    
    print(f"\\n--- 步骤 1: 启动项目服务器 ({project_name}) ---")
    
    server_process = None
    backend_process = None
    original_cwd = Path.cwd()
    print(f"进入前端前当前工作目录: {os.getcwd()}")
    try:
        # 启动前端
        print(f"进入前端前当前工作目录: {os.getcwd()}", flush=True)
        os.chdir(project_path)  # 先切换到项目根目录
        print(f"进入前端前当前工作目录: {os.getcwd()}", flush=True)
        if frontend_path.exists():
            print(f"进入前端前当前工作目录(已到项目根): {os.getcwd()}", flush=True)
            os.chdir(frontend_path)
            print(f"进入前端后当前工作目录: {os.getcwd()}", flush=True)
            print("执行命令: npm install (frontend)")
            install_process = subprocess.run(['npm', 'install'], capture_output=True, text=True, timeout=300)
            if install_process.returncode != 0:
                print("❌ 前端 npm install 失败:", flush=True)
                print("=== STDERR ===")
                print(install_process.stderr, flush=True)
                print("=== STDOUT ===")
                print(install_process.stdout, flush=True)
                return False
            else:
                print("✅ 前端 npm install 成功完成")
                if install_process.stdout.strip():
                    print("=== npm install 输出 ===")
                    print(install_process.stdout.strip())

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
            
            # 检查前端进程启动状态
            if not check_process_startup(server_process, "前端", timeout=10):
                return False
        else:
            print(f"⚠️ 前端目录不存在，跳过前端启动。")
            return False

        # 启动后端
        print(f"进入后端前当前工作目录: {os.getcwd()}")
        os.chdir('..')
        print(f"进入后端目录: {backend_path}")
        os.chdir(backend_path)
        print(f"进入后端后当前工作目录: {os.getcwd()}")
        print("执行命令: npm install (backend)")
        install_process = subprocess.run(['npm', 'install'], capture_output=True, text=True, timeout=300)
        if install_process.returncode != 0:
            print("❌ 后端 npm install 失败:")
            print("=== STDERR ===")
            print(install_process.stderr)
            print("=== STDOUT ===")
            print(install_process.stdout)
            return False
        else:
            print("✅ 后端 npm install 成功完成")
            if install_process.stdout.strip():
                print("=== npm install 输出 ===")
                print(install_process.stdout.strip())

        print("执行命令: npm start (backend)")
        backend_process = subprocess.Popen(
            ['npm', 'start'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid
        )
        print(f"后端服务器进程PID: {backend_process.pid}")
        
        # 检查后端进程启动状态
        if not check_process_startup(backend_process, "后端", timeout=10):
            return False

        # 创建测试任务
        os.chdir(script_dir)
        task_file = create_single_project_tasks(project_name, port, json_line=json_line)
        print(f"📝 已创建测试任务: {task_file}")
        
        # 健康检查
        print(f"\\n--- 步骤 2: 健康检查 ---")
        ports_to_check = [port] # 默认检查前端端口
        if backend_path.exists():
            # 从环境变量读取后端端口，默认为5001
            backend_port = int(os.getenv("BACKEND_PORT", "5001"))
            ports_to_check.append(backend_port) 
        
        if not check_server_health(ports_to_check):
            print("❌ 服务器启动失败")
            return False
        
        # 运行WebVoyager测试
        print(f"\\n--- 步骤 3: 运行 WebVoyager 测试 ---")
        # 将输出目录和任务文件路径构造成绝对路径
        task_file_abs = Path(__file__).parent / task_file
        output_dir_abs = Path(results_dir) / project_name
        
        # 切换到webvoyager目录
        os.chdir(Path(webvoyager_dir))
        
        # 运行WebVoyager
        webvoyager_cmd = [
            'python', 'run.py',
            '--test_file', str(task_file_abs),
            '--headless',
            '--max_iter', os.getenv("WEBVOYAGER_MAX_ITER", "10"),
            '--max_attached_imgs', os.getenv("WEBVOYAGER_MAX_ATTACHED_IMGS", "3"),
            '--temperature', os.getenv("WEBVOYAGER_TEMPERATURE", "0.7"),
            '--output_dir', str(output_dir_abs),
            '--window_width', os.getenv("WEBVOYAGER_WINDOW_WIDTH", "1024"),
            '--window_height', os.getenv("WEBVOYAGER_WINDOW_HEIGHT", "768")
        ]
        
        print(f"执行命令: {' '.join(webvoyager_cmd)}")
        
        # 运行WebVoyager
        result = subprocess.run(webvoyager_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ WebVoyager测试完成")
            print(f"📊 结果保存在: {output_dir_abs}")
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
        print(f"\\n--- 步骤 4: 清理和关闭 ---")
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
    import argparse
    parser = argparse.ArgumentParser(description="手动运行WebVoyager测试单个fullstack项目")
    parser.add_argument(
        "--project-name",
        dest="pname",
        type=str,
        required=True,
        help="通过标志指定项目名称"
    )
    parser.add_argument(
        "--port",
        default=3000,
        type=int,
        help="前端服务器端口 (默认: 3000)"
    )
    parser.add_argument(
        "--test-case-json",
        dest="json_line",
        help="包含测试用例的JSON字符串"
    )
    parser.add_argument(
        "--organized",
        action="store_true",
        help="测试 organized_optimized_code 目录中的项目"
    )
    parser.add_argument(
        "--debug_logged",
        action="store_true",
        help="测试 debug_logged_projects 目录中的项目"
    )
    parser.add_argument(
        "--optimized",
        action="store_true",
        help="测试 optimized_code 目录中的项目"
    )

    args = parser.parse_args()

    project_name = args.pname

    # 确定测试模式
    use_organized = args.organized
    use_debug_logged = args.debug_logged
    use_optimized = args.optimized

    success = run_webvoyager_test(
        project_name, 
        port=args.port, 
        json_line=args.json_line, 
        use_organized=use_organized,
        use_debug_logged=use_debug_logged,
        use_optimized=use_optimized
    )

    if success:
        print(f"✅✅✅ {project_name} 所有测试成功完成！")
        sys.exit(0)
    else:
        print(f"❌❌❌ {project_name} 测试失败。")
        sys.exit(1)

if __name__ == "__main__":
    main()
