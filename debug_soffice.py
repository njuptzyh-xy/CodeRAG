#!/usr/bin/env python3
"""
调试 soffice 命令的脚本
用于测试 LibreOffice 的命令行转换功能
"""

import os
import sys
import subprocess
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_soffice_installation():
    """检查 soffice 是否安装并可用"""
    logger.info("=" * 60)
    logger.info("检查 soffice 安装状态")
    logger.info("=" * 60)

    try:
        # 某些特殊发行版的 soffice --version 会等待输入，导致阻塞（如图）。
        # 为避免“Press Enter to continue...” 卡死（常见于某些绿色版/安装异常情况），
        # 建议用 Popen 立即获取输出并超时后强制终止。
        proc = subprocess.Popen(
            ["soffice", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,  # 防止子进程要求输入
            text=True
        )
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.error("✗ soffice --version 超时，可能程序等待输入（例如 'Press Enter to continue...'）")
            return False
        if proc.returncode == 0:
            logger.info(f"✓ soffice 已安装")
            logger.info(f"版本信息: {stdout.strip()}")
            return True
        else:
            logger.error(f"✗ soffice 执行失败，返回码: {proc.returncode}")
            logger.error(f"stderr: {stderr.strip()}")
            return False
    except FileNotFoundError:
        logger.error("✗ soffice 未找到，请确认 LibreOffice 已安装并添加到 PATH")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ soffice 执行失败: {e}")
        logger.error(f"stderr: {e.stderr}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("✗ soffice 命令超时")
        return False
    except Exception as e:
        logger.error(f"✗ 未知错误: {e}")
        return False


def find_soffice_path():
    """尝试查找 soffice 的安装路径"""
    logger.info("\n" + "=" * 60)
    logger.info("查找 soffice 安装路径")
    logger.info("=" * 60)

    possible_paths = []

    if os.name == "nt":  # Windows
        # 常见的 Windows 安装路径
        program_files = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
            "C:\\Program Files",
            "C:\\Program Files (x86)",
        ]

        for base in program_files:
            paths = [
                os.path.join(base, "LibreOffice", "program", "soffice.exe"),
                os.path.join(base, "LibreOffice", "program", "soffice.com"),
                os.path.join(base, "OpenOffice", "program", "soffice.exe"),
            ]
            possible_paths.extend(paths)
    else:  # Linux/Mac
        possible_paths = [
            "/usr/bin/soffice",
            "/usr/local/bin/soffice",
            "/opt/libreoffice/program/soffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]

    found_paths = []
    for path in possible_paths:
        if os.path.exists(path):
            found_paths.append(path)
            logger.info(f"✓ 找到: {path}")

    if found_paths:
        logger.info(f"\n共找到 {len(found_paths)} 个 soffice 安装")
        return found_paths
    else:
        logger.warning("未找到 soffice 安装路径")
        return []


def check_environment():
    """检查环境变量和 PATH"""
    logger.info("\n" + "=" * 60)
    logger.info("检查环境配置")
    logger.info("=" * 60)

    # 检查 PATH 环境变量
    path_env = os.environ.get("PATH", "")
    logger.info(f"PATH: {path_env}")

    # 在 Windows 上，检查特定路径
    if os.name == "nt":
        logger.info(f"ProgramFiles: {os.environ.get('ProgramFiles', '未设置')}")
        logger.info(f"ProgramFiles(x86): {os.environ.get('ProgramFiles(x86)', '未设置')}")


def test_conversion_command(file_path=None):
    """测试文件转换命令"""
    logger.info("\n" + "=" * 60)
    logger.info("测试转换命令")
    logger.info("=" * 60)

    if file_path and os.path.exists(file_path):
        logger.info(f"测试文件: {file_path}")
    else:
        logger.info("未提供测试文件，仅测试命令格式")

    # 测试不同的命令格式
    test_commands = []

    if os.name == "nt":
        # Windows 下的不同命令格式
        test_commands.extend([
            {
                "name": "列表格式 (推荐)",
                "cmd": ["soffice", "--headless", "--invisible", "--convert-to", "pdf", "--outdir", ".", "test.docx"]
            },
            {
                "name": "Shell 字符串格式",
                "cmd": "soffice --headless --invisible --convert-to pdf test.docx",
                "shell": True
            },
            {
                "name": "带引号的 Shell 字符串",
                "cmd": 'soffice --headless --invisible --convert-to pdf "test document.docx"',
                "shell": True
            }
        ])
    else:
        # Linux/Mac 下的命令格式
        test_commands.extend([
            {
                "name": "列表格式",
                "cmd": ["soffice", "--headless", "--invisible", "--convert-to", "pdf", "--outdir", ".", "test.docx"]
            }
        ])

    for i, test in enumerate(test_commands, 1):
        logger.info(f"\n测试 {i}: {test['name']}")
        logger.info(f"命令: {test['cmd']}")

        if file_path and os.path.exists(file_path):
            # 如果有真实文件，执行真实转换
            output_dir = os.path.dirname(file_path)
            if isinstance(test['cmd'], list):
                cmd = test['cmd'].copy()
                if "--outdir" in cmd:
                    idx = cmd.index("--outdir")
                    cmd[idx + 1] = output_dir
                cmd[-1] = file_path
            else:
                cmd = test['cmd']

            try:
                result = subprocess.run(
                    cmd,
                    shell=test.get('shell', False),
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                logger.info(f"返回码: {result.returncode}")
                if result.stdout:
                    logger.info(f"stdout: {result.stdout}")
                if result.stderr:
                    logger.info(f"stderr: {result.stderr}")

                if result.returncode == 0:
                    logger.info("✓ 转换成功")
                    # 检查输出文件
                    pdf_path = os.path.splitext(file_path)[0] + ".pdf"
                    if os.path.exists(pdf_path):
                        logger.info(f"✓ PDF 文件已生成: {pdf_path}")
                else:
                    logger.warning("✗ 转换失败")
            except Exception as e:
                logger.error(f"✗ 执行错误: {e}")
        else:
            logger.info("（跳过执行，仅显示命令格式）")


def create_test_file():
    """创建测试文件"""
    logger.info("\n" + "=" * 60)
    logger.info("创建测试文件")
    logger.info("=" * 60)

    test_dir = Path("./test_soffice")
    test_dir.mkdir(exist_ok=True)

    # 创建一个简单的文本文件作为测试
    test_file = test_dir / "test.txt"
    test_file.write_text("这是一个测试文件\nThis is a test file.\n", encoding='utf-8')

    logger.info(f"✓ 测试文件已创建: {test_file.absolute()}")
    return str(test_file.absolute())


def main():
    """主函数"""
    logger.info("开始调试 soffice...")
    logger.info(f"操作系统: {os.name}")
    logger.info(f"当前目录: {os.getcwd()}")

    # 1. 检查环境
    check_environment()

    # 2. 检查安装
    is_installed = check_soffice_installation()

    # 3. 如果直接命令失败，尝试查找路径
    if not is_installed:
        paths = find_soffice_path()
        if paths:
            logger.info("\n提示：虽然 soffice 命令不可用，但找到了安装路径")
            logger.info("可能需要将 LibreOffice 的 program 目录添加到 PATH")
            logger.info(f"例如: {os.path.dirname(paths[0])}")

    # 4. 测试转换命令（使用测试文件）
    test_file = create_test_file()
    test_conversion_command(test_file)

    # 5. 提示如何测试真实文件
    logger.info("\n" + "=" * 60)
    logger.info("测试真实文件")
    logger.info("=" * 60)
    logger.info("要测试真实文件，请运行:")
    logger.info(f"  python {__file__} <文件路径>")
    logger.info("例如:")
    logger.info(f"  python {__file__} document.docx")

    # 6. 诊断建议
    logger.info("\n" + "=" * 60)
    logger.info("诊断建议")
    logger.info("=" * 60)

    if not is_installed:
        logger.info("❌ soffice 未安装或不在 PATH 中")
        logger.info("\n解决方案:")
        if os.name == "nt":
            logger.info("1. 安装 LibreOffice: https://www.libreoffice.org/")
            logger.info("2. 将 LibreOffice 安装目录的 program 子目录添加到 PATH")
            logger.info("   例如: C:\\Program Files\\LibreOffice\\program")
            logger.info("3. 或在代码中使用完整路径调用 soffice")
        else:
            logger.info("1. 安装 LibreOffice: sudo apt install libreoffice (Ubuntu/Debian)")
            logger.info("2. 或: sudo yum install libreoffice (CentOS/RHEL)")
            logger.info("3. 或: brew install libreoffice (macOS)")
    else:
        logger.info("✓ soffice 已正确安装")


if __name__ == "__main__":
    # 如果提供了命令行参数，作为测试文件路径
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        if os.path.exists(test_file):
            logger.info(f"使用提供的测试文件: {test_file}")
            test_conversion_command(test_file)
        else:
            logger.error(f"文件不存在: {test_file}")
            sys.exit(1)
    else:
        main()
