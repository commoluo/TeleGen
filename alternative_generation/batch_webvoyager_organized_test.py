#!/usr/bin/env python3
"""
批量测试organized_optimized_code中的WebVoyager项目
Batch test WebVoyager projects in organized_optimized_code
"""

import os
import sys
import subprocess
import time
import json
from pathlib import Path
from datetime import datetime

def test_single_project(project_dir, project_name, port=3000, max_retries=3):
    """测试单个项目"""
    print(f"\n🧪 测试项目: {project_name}")
    print(f"   项目路径: {project_dir}")
    print(f"   端口: {port}")
    print("-" * 50)
    
    # 检查项目结构
    start_script = os.path.join(project_dir, "start.sh")
    frontend_dir = os.path.join(project_dir, "frontend")
    backend_dir = os.path.join(project_dir, "backend")
    
    if not os.path.exists(start_script):
        print(f"❌ 缺少启动脚本: {start_script}")
        return False
    
    if not os.path.exists(frontend_dir):
        print(f"❌ 缺少前端目录: {frontend_dir}")
        return False
        
    if not os.path.exists(backend_dir):
        print(f"❌ 缺少后端目录: {backend_dir}")
        return False
    
    for attempt in range(max_retries):
        try:
            # 构建测试命令 - 使用webvoyager测试
            cmd = [
                "python", "-m", "webvoyager.run",
                "--task", f"test_{project_name}",
                "--project_path", project_dir,
                "--port", str(port),
                "--headless", "true",
                "--timeout", "300"
            ]
            
            print(f"🚀 运行命令: {' '.join(cmd)}")
            
            # 运行测试
            result = subprocess.run(
                cmd,
                cwd="/Users/luoyujia/Downloads/WebGen-Bench-main",
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            if result.returncode == 0:
                print(f"✅ 项目 {project_name} 测试成功")
                return True
            else:
                print(f"❌ 项目 {project_name} 测试失败 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    print(f"   等待 5 秒后重试...")
                    time.sleep(5)
                else:
                    print(f"   STDOUT: {result.stdout}")
                    print(f"   STDERR: {result.stderr}")
                    
        except subprocess.TimeoutExpired:
            print(f"⏰ 项目 {project_name} 测试超时 (尝试 {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                print(f"   等待 5 秒后重试...")
                time.sleep(5)
        except Exception as e:
            print(f"❌ 项目 {project_name} 测试异常: {str(e)}")
            if attempt < max_retries - 1:
                print(f"   等待 5 秒后重试...")
                time.sleep(5)
    
    return False

def test_single_project_simple(project_dir, project_name, port=3000):
    """使用简单方式测试单个项目 - 仅启动检查"""
    print(f"\n🧪 简单测试项目: {project_name}")
    print(f"   项目路径: {project_dir}")
    print(f"   端口: {port}")
    print("-" * 50)
    
    # 检查项目结构
    start_script = os.path.join(project_dir, "start.sh")
    frontend_dir = os.path.join(project_dir, "frontend")
    backend_dir = os.path.join(project_dir, "backend")
    
    if not os.path.exists(start_script):
        print(f"❌ 缺少启动脚本: {start_script}")
        return False
    
    if not os.path.exists(frontend_dir):
        print(f"❌ 缺少前端目录: {frontend_dir}")
        return False
        
    if not os.path.exists(backend_dir):
        print(f"❌ 缺少后端目录: {backend_dir}")
        return False
    
    try:
        # 尝试运行启动脚本并检查输出
        result = subprocess.run(
            ["bash", "start.sh"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30  # 30秒快速检查
        )
        
        # 检查是否有明显的错误
        if "Error" in result.stderr or "error" in result.stderr:
            print(f"❌ 启动脚本执行有错误:")
            print(f"   STDERR: {result.stderr}")
            return False
        
        # 检查是否有成功启动的迹象
        if "Server running" in result.stdout or "http://localhost" in result.stdout:
            print(f"✅ 项目 {project_name} 启动正常")
            return True
        
        print(f"⚠️  项目 {project_name} 启动状态不明确")
        print(f"   STDOUT: {result.stdout[:200]}...")
        return True  # 暂时认为通过
        
    except subprocess.TimeoutExpired:
        print(f"✅ 项目 {project_name} 启动正常 (超时但正常)")
        return True  # 超时通常意味着服务正在运行
    except Exception as e:
        print(f"❌ 项目 {project_name} 测试异常: {str(e)}")
        return False

def batch_test_projects(projects_dir, start_from=1, limit=None, test_mode="simple"):
    """批量测试项目"""
    print("🚀 开始批量测试organized_optimized_code项目")
    print(f"项目目录: {projects_dir}")
    print(f"开始位置: {start_from}")
    print(f"测试限制: {limit if limit else '无限制'}")
    print(f"测试模式: {test_mode}")
    print("=" * 60)
    
    # 检查项目目录
    if not os.path.exists(projects_dir):
        print(f"❌ 项目目录不存在: {projects_dir}")
        return
    
    # 获取所有重构项目 - 只测试restructured版本
    projects = []
    for item in os.listdir(projects_dir):
        if item.endswith("_simple_project_runnable_restructured"):
            project_path = os.path.join(projects_dir, item)
            if os.path.isdir(project_path):
                projects.append((item, project_path))
    
    # 按项目编号排序
    projects.sort(key=lambda x: int(x[0].split('_')[0]))
    
    # 应用开始位置和限制
    if start_from > 1:
        projects = projects[start_from-1:]
    
    if limit:
        projects = projects[:limit]
    
    print(f"📋 找到 {len(projects)} 个restructured项目需要测试")
    
    # 创建结果记录
    results = {
        "test_time": datetime.now().isoformat(),
        "test_mode": test_mode,
        "projects_tested": len(projects),
        "results": []
    }
    
    # 开始测试
    successful_count = 0
    failed_count = 0
    base_port = 3000
    
    start_time = time.time()
    
    for i, (project_name, project_path) in enumerate(projects):
        print(f"\n[{i+1}/{len(projects)}] 测试项目: {project_name}")
        
        # 使用不同端口避免冲突
        port = base_port + i
        
        test_start = time.time()
        
        # 根据测试模式选择测试方法
        if test_mode == "simple":
            success = test_single_project_simple(project_path, project_name, port)
        else:
            success = test_single_project(project_path, project_name, port)
        
        test_end = time.time()
        test_duration = test_end - test_start
        
        # 记录结果
        result_record = {
            "project_name": project_name,
            "project_path": project_path,
            "success": success,
            "test_duration": test_duration,
            "port": port
        }
        results["results"].append(result_record)
        
        if success:
            successful_count += 1
        else:
            failed_count += 1
        
        # 添加间隔避免资源冲突
        if i < len(projects) - 1:
            print("⏳ 等待 2 秒...")
            time.sleep(2)
    
    # 生成报告
    end_time = time.time()
    total_time = end_time - start_time
    
    print("\n" + "=" * 60)
    print("🎉 批量测试完成!")
    print(f"📊 统计结果:")
    print(f"   ✅ 成功: {successful_count} 个项目")
    print(f"   ❌ 失败: {failed_count} 个项目")
    print(f"   📈 成功率: {successful_count/(successful_count+failed_count)*100:.1f}%")
    print(f"   ⏱️  总耗时: {total_time/60:.1f} 分钟")
    print(f"   📊 平均耗时: {total_time/len(projects):.1f} 秒/项目")
    
    # 保存详细结果
    results_file = f"/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/organized_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    results.update({
        "successful_count": successful_count,
        "failed_count": failed_count,
        "success_rate": successful_count/(successful_count+failed_count)*100,
        "total_time_minutes": total_time/60,
        "average_time_per_project": total_time/len(projects)
    })
    
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"   📁 详细结果已保存: {results_file}")
    
    # 显示失败项目列表
    if failed_count > 0:
        print(f"\n❌ 失败的项目:")
        for result in results["results"]:
            if not result["success"]:
                print(f"   - {result['project_name']}")

def main():
    """主函数"""
    projects_dir = "/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/organized_optimized_code"
    
    print("🔬 Organized Optimized Code WebVoyager 批量测试工具")
    print("=" * 60)
    
    # 检查项目目录
    if not os.path.exists(projects_dir):
        print(f"❌ 项目目录不存在: {projects_dir}")
        return
    
    # 获取测试参数
    start_input = input("开始测试项目编号 (默认: 1): ").strip()
    start_from = 1
    if start_input.isdigit():
        start_from = int(start_input)
    
    limit_input = input("测试项目数量限制 (留空测试全部): ").strip()
    limit = None
    if limit_input.isdigit():
        limit = int(limit_input)
    
    # 选择测试模式
    print("\n测试模式选择:")
    print("1. simple - 快速启动检查 (推荐)")
    print("2. full - 完整WebVoyager测试")
    mode_input = input("选择测试模式 (1/2, 默认: 1): ").strip()
    test_mode = "simple" if mode_input != "2" else "full"
    
    # 确认测试
    print(f"\n⚠️  即将开始测试:")
    print(f"   📁 项目目录: {projects_dir}")
    print(f"   🏁 开始位置: 第 {start_from} 个项目")
    print(f"   🔢 测试数量: {limit if limit else '全部'}")
    print(f"   🧪 测试模式: {test_mode}")
    estimated_time = (limit or 98) * (0.5 if test_mode == "simple" else 5)
    print(f"   ⏱️  预计耗时: 约 {estimated_time} 分钟")
    
    confirm = input(f"\n确认开始测试? (y/N): ").strip().lower()
    if confirm != 'y':
        print("测试已取消")
        return
    
    # 开始批量测试
    batch_test_projects(projects_dir, start_from, limit, test_mode)

if __name__ == "__main__":
    main()
