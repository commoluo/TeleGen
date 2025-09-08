"""
将 alternative_generation/generated_websites/organized_runs 中的 backend.js 文件
复制到 alternative_generation/debug_logged_projects 对应的项目文件夹中。
"""
import os
import shutil
from pathlib import Path
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def copy_backend_files():
    """将 organized_runs 中的 backend.js 复制到 debug_logged_projects 目录"""
    
    # 源目录和目标目录
    source_base = Path("/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/generated_websites/organized_runs")
    target_base = Path("/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/debug_logged_projects")
    
    if not source_base.exists():
        logger.error(f"源目录不存在: {source_base}")
        return
    
    if not target_base.exists():
        logger.info(f"目标目录不存在，将创建: {target_base}")
        target_base.mkdir(parents=True, exist_ok=True)

    # 获取所有源项目目录
    source_projects = []
    for project_dir in source_base.glob("full_run_with_api_doc_*"):
        if project_dir.is_dir():
            backend_file = project_dir / "backend.js"
            if backend_file.exists():
                source_projects.append(project_dir)
    
    # 按项目ID排序
    source_projects.sort(key=lambda x: x.name)
    
    logger.info(f"找到 {len(source_projects)} 个包含 backend.js 的源项目")
    
    copied_count = 0
    skipped_count = 0
    error_count = 0
    
    for source_project in source_projects:
        project_name = source_project.name  # 格式: full_run_with_api_doc_001
        source_backend = source_project / "backend.js"
        
        # 目标项目名称与源项目名称相同
        target_project_name = project_name
        target_project_dir = target_base / target_project_name
        target_backend = target_project_dir / "backend.js"
        
        try:
            # 确保目标项目目录存在
            if not target_project_dir.exists():
                logger.info(f"目标项目目录不存在，将创建: {target_project_dir}")
                target_project_dir.mkdir(parents=True, exist_ok=True)
            
            # 复制 backend.js 文件
            shutil.copy2(source_backend, target_backend)
            logger.info(f"✅ 复制成功: {project_name}/backend.js -> {target_project_name}/backend.js")
            copied_count += 1
            
        except Exception as e:
            logger.error(f"❌ 复制失败 {project_name} -> {target_project_name}/backend.js: {e}")
            error_count += 1
    
    # 总结报告
    logger.info(f"📊 复制完成:")
    logger.info(f"   ✅ 成功: {copied_count}")
    logger.info(f"   ⚠️  跳过: {skipped_count}")
    logger.info(f"   ❌ 失败: {error_count}")
    logger.info(f"   📦 总计: {len(source_projects)}")

def verify_copies():
    """验证复制结果"""
    target_base = Path("/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/debug_logged_projects")
    
    if not target_base.exists():
        logger.error("目标目录不存在")
        return
    
    verified_count = 0
    for project_dir in target_base.glob("full_run_with_api_doc_*"):
        if project_dir.is_dir():
            backend_file = project_dir / "backend.js"
            if backend_file.exists():
                verified_count += 1
                logger.debug(f"✓ 验证通过: {project_dir.name}/backend.js")
    
    logger.info(f"🔍 验证结果: {verified_count} 个项目包含 backend.js 文件")

def main():
    copy_backend_files()
    verify_copies()

if __name__ == "__main__":
    main()
import os
import shutil
from pathlib import Path
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def copy_backend_files():
    """复制 backend.js 文件到调试项目目录"""
    
    # 源目录和目标目录
    source_base = Path("/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/generated_websites/fullstack_projects_20250717_174459")
    target_base = Path("/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/organized_optimized_code")
    
    if not source_base.exists():
        logger.error(f"源目录不存在: {source_base}")
        return
    
    if not target_base.exists():
        logger.error(f"目标目录不存在: {target_base}")
        return
    
    # 获取所有源项目目录
    source_projects = []
    for project_dir in source_base.glob("*_simple_project"):
        if project_dir.is_dir():
            backend_file = project_dir / "backend.js"
            if backend_file.exists():
                source_projects.append(project_dir)
    
    # 按项目ID排序
    source_projects.sort(key=lambda x: x.name)
    
    logger.info(f"找到 {len(source_projects)} 个包含 backend.js 的源项目")
    
    copied_count = 0
    skipped_count = 0
    error_count = 0
    
    for source_project in source_projects:
        project_name = source_project.name  # 格式: 001_simple_project
        source_backend = source_project / "backend.js"
        
        # 构建目标项目名称: 001_simple_project -> 001_simple_project_runnable
        target_project_name = project_name + "_runnable"
        target_project = target_base / target_project_name
        target_backend = target_project / "backend.js"
        
        try:
            # 检查目标项目目录是否存在
            if not target_project.exists():
                logger.warning(f"目标项目目录不存在，跳过: {project_name} -> {target_project_name}")
                skipped_count += 1
                continue
            
            # 复制 backend.js 文件
            shutil.copy2(source_backend, target_backend)
            logger.info(f"✅ 复制成功: {project_name} -> {target_project_name}/backend.js")
            copied_count += 1
            
        except Exception as e:
            logger.error(f"❌ 复制失败 {project_name} -> {target_project_name}/backend.js: {e}")
            error_count += 1
    
    # 总结报告
    logger.info(f"\n📊 复制完成:")
    logger.info(f"   ✅ 成功: {copied_count}")
    logger.info(f"   ⚠️  跳过: {skipped_count}")
    logger.info(f"   ❌ 失败: {error_count}")
    logger.info(f"   📦 总计: {len(source_projects)}")

def verify_copies():
    """验证复制结果"""
    target_base = Path("/Users/luoyujia/Downloads/WebGen-Bench-main/alternative_generation/debug_logged_projects")
    
    if not target_base.exists():
        logger.error("目标目录不存在")
        return
    
    verified_count = 0
    for project_dir in target_base.glob("*_simple_project"):
        if project_dir.is_dir():
            backend_file = project_dir / "backend.js"
            if backend_file.exists():
                verified_count += 1
                logger.debug(f"✓ 验证通过: {project_dir.name}/backend.js")
    
    logger.info(f"🔍 验证结果: {verified_count} 个项目包含 backend.js 文件")

def main():
    """主函数"""
    logger.info("开始复制 backend.js 文件...")
    copy_backend_files()
    
    logger.info("\n开始验证复制结果...")
    verify_copies()
    
    logger.info("\n🎉 任务完成!")

if __name__ == "__main__":
    main()
