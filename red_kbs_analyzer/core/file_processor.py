"""
文件处理器模块
负责扫描项目文件、过滤代码文件、提取文件内容
"""
import os
from pathlib import Path
from typing import List, Dict, Any, Set
from ..models.analysis import CodeFile
from ..run_logs.logger import logger

class FileProcessor:
    """文件处理器"""
    
    # 支持的代码文件扩展名
    CODE_EXTENSIONS = {
        '.py', '.java', '.c', '.cpp', '.h', '.hpp', '.go', '.rs', 
        '.cs', '.js', '.ts', '.sh', '.ps1', '.rb', '.php', '.swift',
        '.kt', '.scala', '.r', '.pl', '.lua', '.m', '.mm'
    }
    
    # 忽略的目录
    IGNORE_DIRS = {
        '.git', '.svn', '.hg', '__pycache__', 'node_modules', 
        '.vscode', '.idea', 'build', 'dist', 'target', 'bin', 'obj',
        '.pytest_cache', '.mypy_cache', 'venv', 'env', '.env'
    }
    
    # 忽略的文件
    IGNORE_FILES = {
        '.gitignore', '.gitattributes', '.DS_Store', 'Thumbs.db',
        '.pylintrc', '.flake8', 'pytest.ini', 'setup.cfg', 'tox.ini'
    }
    
    def __init__(self, max_file_size: int = 1024 * 1024):  # 1MB
        """
        初始化文件处理器
        
        Args:
            max_file_size: 最大文件大小限制（字节）
        """
        self.max_file_size = max_file_size
    
    def scan_project(self, project_path: str, project_name: str) -> List[CodeFile]:
        """
        扫描项目目录，返回代码文件列表
        
        Args:
            project_path: 项目路径
            project_name: 项目名称
            
        Returns:
            代码文件列表
        """
        project_path = Path(project_path)
        if not project_path.exists() or not project_path.is_dir():
            raise ValueError(f"项目路径不存在或不是目录: {project_path}")
        
        code_files = []
        
        for file_path in self._walk_directory(project_path):
            try:
                if self._is_code_file(file_path) and self._is_valid_file(file_path):
                    code_file = self._create_code_file(file_path, project_path, project_name)
                    if code_file:
                        code_files.append(code_file)
            except Exception as e:
                logger.error(f"处理文件 {file_path} 时出错: {e}")
                continue
        
        return code_files
    
    def _walk_directory(self, directory: Path) -> List[Path]:
        """遍历目录，返回所有文件路径"""
        files = []
        
        for item in directory.rglob('*'):
            if item.is_file():
                # 检查是否在忽略的目录中
                if any(ignore_dir in item.parts for ignore_dir in self.IGNORE_DIRS):
                    continue
                # 检查是否是忽略的文件
                if item.name in self.IGNORE_FILES:
                    continue
                files.append(item)
        
        return files
    
    def _is_code_file(self, file_path: Path) -> bool:
        """判断是否为代码文件"""
        return file_path.suffix.lower() in self.CODE_EXTENSIONS
    
    def _is_valid_file(self, file_path: Path) -> bool:
        """判断文件是否有效（大小限制等）"""
        try:
            file_size = file_path.stat().st_size
            return file_size <= self.max_file_size
        except OSError:
            return False
    
    def _create_code_file(self, file_path: Path, project_root: Path, project_name: str) -> CodeFile:
        """创建代码文件对象"""
        try:
            rel_path = file_path.relative_to(project_root)
            file_size = file_path.stat().st_size
            
            return CodeFile(
                file_path=str(rel_path),
                file_abs_path=str(file_path),
                file_name=file_path.name,
                file_size=file_size,
                file_type=self._get_file_type(file_path),
                project_root=str(project_root),
                project_name=project_name
            )
        except Exception as e:
            logger.error(f"创建代码文件对象失败 {file_path}: {e}")
            return None
    
    def _get_file_type(self, file_path: Path) -> str:
        """获取文件类型"""
        return "code"
    
    def read_file_content(self, file_path: str) -> str:
        """
        读取文件内容，支持多种编码
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件内容
        """
        encodings = ['utf-8', 'gbk', 'gb18030', 'iso-8859-1', 'latin-1']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.error(f"读取文件 {file_path} 出错: {e}")
                return ""
        
        logger.error(f"无法用任何支持的编码方式读取文件: {file_path}")
        return "" 