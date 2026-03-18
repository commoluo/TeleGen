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
import shutil
import requests
from dotenv import load_dotenv
from pathlib import Path


def run_npm_install_with_retries(component_name, timeout=300):
    """执行 npm install，失败时自动重试 --force 与 --legacy-peer-deps。"""
    attempts = [
        ["npm", "install"],
        ["npm", "install", "--force"],
        ["npm", "install", "--legacy-peer-deps"],
    ]
    logs = []
    last_process = None

    for idx, cmd in enumerate(attempts, start=1):
        cmd_text = " ".join(cmd)
        print(f"执行命令: {cmd_text} ({component_name}, attempt {idx}/{len(attempts)})")
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        last_process = process

        logs.append(
            f"=== Attempt {idx}: {cmd_text} ===\n"
            f"Return Code: {process.returncode}\n"
            f"--- STDOUT ---\n{process.stdout or ''}\n"
            f"--- STDERR ---\n{process.stderr or ''}\n"
        )

        if process.returncode == 0:
            return True, process, "\n".join(logs)

        print(f"⚠️ {component_name} install attempt {idx} 失败，退出码: {process.returncode}")

    return False, last_process, "\n".join(logs)

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

def handle_install_failure(project_name, port, json_line, component, results_dir, script_dir,
                           install_process=None, stage="failure", stdout=None, stderr=None,
                           error_message=None):
    """在发生错误时，确保生成任务文件、结果目录并记录详细日志。"""
    try:
        print(f"🛠️ 正在记录 {component} 阶段的失败日志 ({stage})...")
        original_cwd = Path.cwd()
        try:
            os.chdir(script_dir)
            task_file = create_single_project_tasks(project_name, port, json_line=json_line)
        finally:
            os.chdir(original_cwd)

        task_file_path = Path(script_dir) / task_file
        output_dir = Path(results_dir) / project_name
        output_dir.mkdir(parents=True, exist_ok=True)

        # 复制任务文件，方便后续调试
        task_file_destination = output_dir / task_file_path.name
        try:
            shutil.copyfile(task_file_path, task_file_destination)
        except Exception as copy_err:
            print(f"⚠️ 复制任务文件到结果目录时出错: {copy_err}")

        log_file_path = output_dir / f"{component}_{stage}_failure_log.txt"
        captured_stdout = stdout if stdout is not None else (install_process.stdout if install_process else "")
        captured_stderr = stderr if stderr is not None else (install_process.stderr if install_process else "")
        return_code = None
        if install_process is not None:
            return_code = install_process.returncode

        with open(log_file_path, 'w', encoding='utf-8') as log_file:
            log_file.write(f"Component: {component}\n")
            log_file.write(f"Stage: {stage}\n")
            if return_code is not None:
                log_file.write(f"Return Code: {return_code}\n")
            if error_message:
                log_file.write(f"Error Message: {error_message}\n")
            log_file.write("\n" + "=" * 20 + " STDOUT " + "=" * 20 + "\n")
            log_file.write(captured_stdout or "No stdout.")
            log_file.write("\n" + "=" * 20 + " STDERR " + "=" * 20 + "\n")
            log_file.write(captured_stderr or "No stderr.")

        print(f"✅ 失败日志已保存到: {log_file_path}")
    except Exception as err:
        print(f"⚠️ 记录安装失败信息时发生异常: {err}")

def should_skip_existing_results(project_name, results_dir):
    """检查是否已经存在测试结果文件，若存在则跳过本次测试。"""
    try:
        output_dir = Path(results_dir) / project_name
        if output_dir.exists() and any(output_dir.iterdir()):
            print(f"⏭️ 检测到已有测试结果目录: {output_dir}，将跳过该项目的测试。")
            return True
    except Exception as e:
        print(f"⚠️ 检查已有结果目录时出错: {e}")
    return False

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
    """检查进程是否成功启动，返回 (is_ok, stdout, stderr)。"""
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
            return False, stdout, stderr

        time.sleep(1)

    print(f"✅ {name}进程启动正常，PID: {process.pid}")
    return True, "", ""

def run_webvoyager_test(project_name, port=3000, json_line=None, use_organized=False, use_debug_logged=False, use_optimized=False):
    """运行WebVoyager测试"""
    
    script_dir = Path(__file__).parent
    print(f"--- 步骤 1: 加载环境变量 ---")
    env_path = script_dir / '.env'
    if not env_path.exists():
        print(f"❌ 错误: .env 文件未找到于 {env_path}")
        default_results_root = Path(__file__).parent.parent / "webvoyager" / "webvoyager_results"
        handle_install_failure(
            project_name, port, json_line,
            component="environment",
            results_dir=str(default_results_root),
            script_dir=Path(__file__).parent,
            stage="env_missing",
            error_message=f".env not found at {env_path}"
        )
        return False
    load_dotenv(dotenv_path=env_path)

    # 不再强制要求API key，交由webvoyager自动处理
    print("✅ .env环境变量已加载，API Key将由WebVoyager自动读取。")

    # 从 .env 或使用默认值获取配置
    
    if use_organized:
        # 使用organized_optimized_code目录
        projects_dir = Path(os.getenv("ORGANIZED_PROJECTS_DIR", str(script_dir / "organized_optimized_code")))
        print(f"使用organized模式，项目目录: {projects_dir}")
    elif use_debug_logged:
        # 使用debug_logged_projects目录
        projects_dir = Path(os.getenv("DEBUG_LOGGED_PROJECTS_DIR", str(script_dir / "debug_logged_projects")))
        print(f"使用debug_logged模式，项目目录: {projects_dir}")
    elif use_optimized:
        # 使用optimized_code目录
        projects_dir = Path(os.getenv("OPTIMIZED_PROJECTS_DIR", str(script_dir / "optimized_code")))
        print(f"使用optimized模式，项目目录: {projects_dir}")
    else:
        # projects_dir现在使用绝对路径，防止工作目录影响
        projects_dir = os.getenv(
            "PROJECTS_DIR",
            str(script_dir / "generated_websites" / "fullstack_projects")
        )
    
    webvoyager_dir = os.getenv("WEBVOYAGER_DIR", str(script_dir.parent / "webvoyager"))
    default_results_dir = script_dir.parent / "webvoyager" / "webvoyager_results"
    results_dir = os.getenv("RESULTS_DIR", str(default_results_dir))

    if use_organized or use_debug_logged or use_optimized:
        # 对于 organized, debug_logged, optimized 模式，直接使用project_name
        real_project_name = project_name
    else:
        # 新增：自动转换id为实际目录名
        real_project_name = id_to_project_dir(project_name)
    
    project_path = Path(projects_dir) / real_project_name

    if not project_path.exists():
        print(f"❌ 错误: 项目不存在: {project_path}")
        handle_install_failure(
            project_name, port, json_line,
            component="project",
            results_dir=results_dir,
            script_dir=script_dir,
            stage="missing_project",
            error_message=f"Project path not found: {project_path}"
        )
        return False

    # 若已有测试结果，直接跳过
    if should_skip_existing_results(project_name, results_dir):
        return True

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
    task_file = f"./webvoyager_task_{project_name}.jsonl"
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
            frontend_ok, install_process, frontend_install_logs = run_npm_install_with_retries("frontend", timeout=300)
            if not frontend_ok:
                print("❌ 前端 npm install 失败:", flush=True)
                print(frontend_install_logs, flush=True)
                handle_install_failure(
                    project_name, port, json_line,
                    component="frontend",
                    results_dir=results_dir,
                    script_dir=script_dir,
                    install_process=install_process,
                    stage="npm_install",
                    stdout=frontend_install_logs,
                    stderr="",
                    error_message="frontend npm install failed"
                )
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
            frontend_ok, frontend_stdout, frontend_stderr = check_process_startup(server_process, "前端", timeout=10)
            if not frontend_ok:
                handle_install_failure(
                    project_name, port, json_line,
                    component="frontend",
                    results_dir=results_dir,
                    script_dir=script_dir,
                    stage="startup",
                    stdout=frontend_stdout,
                    stderr=frontend_stderr,
                    error_message="frontend process exited unexpectedly"
                )
                return False
        else:
            print(f"⚠️ 前端目录不存在，跳过前端启动。")
            handle_install_failure(
                project_name, port, json_line,
                component="frontend",
                results_dir=results_dir,
                script_dir=script_dir,
                stage="missing_directory",
                error_message="frontend directory not found"
            )
            return False

        # 启动后端
        print(f"进入后端前当前工作目录: {os.getcwd()}")
        os.chdir('..')
        print(f"进入后端目录: {backend_path}")
        os.chdir(backend_path)
        print(f"进入后端后当前工作目录: {os.getcwd()}")
        backend_ok, install_process, backend_install_logs = run_npm_install_with_retries("backend", timeout=300)
        if not backend_ok:
            print("❌ 后端 npm install 失败:")
            print(backend_install_logs)
            handle_install_failure(
                project_name, port, json_line,
                component="backend",
                results_dir=results_dir,
                script_dir=script_dir,
                install_process=install_process,
                stage="npm_install",
                stdout=backend_install_logs,
                stderr="",
                error_message="backend npm install failed"
            )
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
        backend_ok, backend_stdout, backend_stderr = check_process_startup(backend_process, "后端", timeout=10)
        if not backend_ok:
            handle_install_failure(
                project_name, port, json_line,
                component="backend",
                results_dir=results_dir,
                script_dir=script_dir,
                stage="startup",
                stdout=backend_stdout,
                stderr=backend_stderr,
                error_message="backend process exited unexpectedly"
            )
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
            handle_install_failure(
                project_name, port, json_line,
                component="services",
                results_dir=results_dir,
                script_dir=script_dir,
                stage="health_check",
                error_message=f"Port readiness failed for {ports_to_check}"
            )
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
            '--api_model', os.getenv("WEBVOYAGER_API_MODEL", "qwen3.5-flash"),
            '--output_dir', str(output_dir_abs),
            '--window_width', os.getenv("WEBVOYAGER_WINDOW_WIDTH", "1024"),
            '--window_height', os.getenv("WEBVOYAGER_WINDOW_HEIGHT", "768")
        ]

        api_base_url = os.getenv("WEBVOYAGER_API_BASE_URL")
        if api_base_url:
            webvoyager_cmd.extend(['--api_base_url', api_base_url])
        
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
            handle_install_failure(
                project_name, port, json_line,
                component="webvoyager",
                results_dir=results_dir,
                script_dir=script_dir,
                stage="run",
                stdout=result.stdout,
                stderr=result.stderr,
                error_message="WebVoyager execution failed"
            )
        
        return result.returncode == 0
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        handle_install_failure(
            project_name, port, json_line,
            component="test_runner",
            results_dir=results_dir,
            script_dir=script_dir,
            stage="exception",
            error_message=str(e)
        )
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
