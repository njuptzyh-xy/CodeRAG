import os
from pathlib import Path
import pathlib
import re
import shutil
import sys
import subprocess

import time
import uuid
import requests
from typing import Optional, Dict, Any, List,Tuple
from urllib.parse import quote
from datetime import datetime
import stat
from neo4j import GraphDatabase
from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    Function,
    FunctionType,
    utility,
)
from pymilvus.exceptions import MilvusException
from setting import (
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    NEO4J_DATABASE,
    MILVUS_HOST,
    MILVUS_PORT,
    MILVUS_USER,
    MILVUS_PASSWORD,
    MILVUS_DB_NAME,
    MILVUS_COLLECTION,
    MILVUS_CONSISTENCY_LEVEL,
    MILVUS_SECURE,
)

# Gitea 配置
GITEA_URL = os.getenv('GITEA_URL', 'http://10.1.1.155:3000')
GITEA_ADMIN_USER = os.getenv('GITEA_ADMIN_USER', 'root')
GITEA_ADMIN_PASSWORD = os.getenv('GITEA_ADMIN_PASSWORD', 'Admin@1234')
GITEA_ORG_NAME = os.getenv('GITEA_ORG_NAME', 'red_team_rag')

AUTH = (NEO4J_USER, NEO4J_PASSWORD)
SESSION_KWARGS = {"database": NEO4J_DATABASE}
driver = GraphDatabase.driver(NEO4J_URI, auth=AUTH)

 # 支持的代码文件扩展名
CODE_EXTENSIONS = {
    '.py', '.java', '.c', '.cpp', '.h', '.hpp', '.go', '.rs', 
    '.cs', '.js', '.ts', '.sh', '.ps1', '.rb', '.php', '.swift',
    '.kt', '.scala', '.r', '.pl', '.lua', '.m', '.mm'
}
max_file_size = 1024 * 1024

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


# 连接 Milvus - 改进错误处理
milvus_connected = False
try:
    connections.connect(
        alias="default",
        host=MILVUS_HOST,
        port=str(MILVUS_PORT),
        user=MILVUS_USER,
        password=MILVUS_PASSWORD,
        db_name=MILVUS_DB_NAME,
        secure=MILVUS_SECURE,
    )
    milvus_connected = True
    print(f"Milvus 连接成功: {MILVUS_HOST}:{MILVUS_PORT}")
except Exception as e:
    print(f"Milvus 连接失败: {e}")
    print(
        f"连接参数: host={MILVUS_HOST}, port={MILVUS_PORT}, user={MILVUS_USER}, db={MILVUS_DB_NAME}"
    )


class GiteaService:
    """Gitea 服务类，用于与 Gitea API 交互"""

    def __init__(self, base_url: str, username: str, password: str):
        """
        初始化 Gitea 服务

        Args:
            base_url: Gitea 服务地址
            username: 管理员用户名
            password: 管理员密码
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.token: Optional[str] = None
        self.session = requests.Session()

    def _get_api_url(self, endpoint: str) -> str:
        """构建完整的 API URL"""
        return f"{self.base_url}/api/v1{endpoint}"

    def authenticate(self) -> bool:
        """
        使用用户名和密码进行认证，获取 token

        Returns:
            认证成功返回 True，失败返回 False
        """
        try:
            auth_url = self._get_api_url(f"/users/{self.username}/tokens")
            auth_data = {
                "name": "api_token_batch_upload",
                "scopes": ["write:repository", "read:repository", "write:organization"]
            }

            response = self.session.post(
                auth_url,
                json=auth_data,
                auth=(self.username, self.password),
                timeout=10
            )

            if response.status_code == 201:
                self.token = response.json().get("sha1")
                print(f"[OK] 认证成功，获取到 token")
                return True
            elif response.status_code == 200:
                print(f"[INFO] Token 可能已存在，使用 Basic Auth")
                self.token = None
                return True
            else:
                print(f"[INFO] Token 创建失败，尝试使用 Basic Auth: HTTP {response.status_code}")
                self.token = None
                return True

        except Exception as exc:
            print(f"[WARN] 认证异常，将使用 Basic Auth: {exc}")
            self.token = None
            return True

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    def _get_auth(self) -> tuple:
        """获取 Basic Auth 凭证"""
        return (self.username, self.password)

    def get_org(self, org_name: str) -> Optional[Dict[str, Any]]:
        """获取组织信息"""
        try:
            get_url = self._get_api_url(f"/orgs/{org_name}")

            if self.token:
                response = self.session.get(
                    get_url,
                    headers=self._get_headers(),
                    timeout=10
                )
            else:
                response = self.session.get(
                    get_url,
                    auth=self._get_auth(),
                    timeout=10
                )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                print(f"[WARN] 获取组织信息失败: HTTP {response.status_code}")
                return None

        except Exception as exc:
            print(f"[WARN] 获取组织信息异常: {exc}")
            return None

    def ensure_org_exists(self, org_name: str) -> bool:
        """确保组织存在，如果不存在则创建"""
        org_info = self.get_org(org_name)
        if org_info:
            print(f"[INFO] 组织已存在: {org_name}")
            return True

        print(f"[INFO] 组织不存在，正在创建: {org_name}")
        try:
            create_url = self._get_api_url("/orgs")
            org_data = {
                "username": org_name,
                "visibility": "public"
            }

            if self.token:
                response = self.session.post(
                    create_url,
                    json=org_data,
                    headers=self._get_headers(),
                    timeout=30
                )
            else:
                response = self.session.post(
                    create_url,
                    json=org_data,
                    auth=self._get_auth(),
                    timeout=30
                )

            if response.status_code in [201, 200]:
                print(f"[OK] 组织创建成功: {org_name}")
                return True
            else:
                error_msg = response.text
                if response.status_code == 422:
                    # 可能是组织已存在
                    print(f"[WARN] 创建组织失败，可能已存在: HTTP {response.status_code}")
                    return self.get_org(org_name) is not None
                else:
                    print(f"[FAIL] 创建组织失败: HTTP {response.status_code} - {error_msg}")
                    return False

        except Exception as exc:
            print(f"[FAIL] 创建组织异常: {exc}")
            return False

    def create_repo(
        self,
        repo_name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
        org_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        创建仓库（项目）

        Args:
            repo_name: 仓库名称
            description: 仓库描述
            private: 是否为私有仓库
            auto_init: 是否自动初始化仓库（设为 False，因为我们要手动推送）
            org_name: 组织名称，如果提供则在组织下创建，否则在用户下创建

        Returns:
            成功返回仓库信息字典，失败返回 None
        """
        try:
            if org_name:
                create_url = self._get_api_url(f"/orgs/{org_name}/repos")
            else:
                create_url = self._get_api_url("/user/repos")

            repo_data = {
                "name": repo_name,
                "description": description,
                "private": private,
                "auto_init": auto_init
            }

            if self.token:
                response = self.session.post(
                    create_url,
                    json=repo_data,
                    headers=self._get_headers(),
                    timeout=30
                )
            else:
                response = self.session.post(
                    create_url,
                    json=repo_data,
                    auth=self._get_auth(),
                    timeout=30
                )

            if response.status_code in [201, 200]:
                repo_info = response.json()
                print(f"[OK] 仓库创建成功: {repo_name}")
                return repo_info
            elif response.status_code == 409:
                print(f"[WARN] 仓库已存在: {repo_name}")
                # 获取现有仓库信息
                if org_name:
                    repo_path = f"{org_name}/{repo_name}"
                else:
                    repo_path = f"{self.username}/{repo_name}"
                get_url = self._get_api_url(f"/repos/{repo_path}")
                if self.token:
                    resp = self.session.get(get_url, headers=self._get_headers(), timeout=10)
                else:
                    resp = self.session.get(get_url, auth=self._get_auth(), timeout=10)
                if resp.status_code == 200:
                    return resp.json()
                return None
            else:
                print(f"[FAIL] 创建仓库失败: HTTP {response.status_code} - {response.text}")
                return None

        except Exception as exc:
            print(f"[FAIL] 创建仓库异常: {exc}")
            return None

    def get_repo_clone_url(self, repo_info: Dict[str, Any]) -> str:
        """获取仓库的克隆 URL（带认证信息，密码做 URL 编码）"""
        clone_url = repo_info.get('clone_url', '')
        if not clone_url:
            return ''

        # 将 http:// 替换为带认证信息的 URL
        # 格式: http://username:password@host/path
        # 注意：password 需要做 URL 编码，避免其中的 @、: 等特殊字符破坏 URL 结构
        encoded_password = quote(self.password, safe='')

        if clone_url.startswith('http://'):
            url_part = clone_url.replace('http://', '')
            return f"http://{self.username}:{encoded_password}@{url_part}"
        elif clone_url.startswith('https://'):
            url_part = clone_url.replace('https://', '')
            return f"https://{self.username}:{encoded_password}@{url_part}"
        return clone_url


def get_subfolders(base_path: str) -> List[str]:
    """
    获取指定路径下的所有子文件夹

    Args:
        base_path: 基础路径

    Returns:
        子文件夹路径列表
    """
    try:
        subfolders = []
        for item in os.listdir(base_path):
            item_path = os.path.join(base_path, item)
            if os.path.isdir(item_path):
                subfolders.append(item_path)
        return sorted(subfolders)
    except Exception as e:
        print(f"[FAIL] 扫描文件夹失败: {e}")
        return []

def handle_reponame(file_name: str) -> str:
    repo_name_base = os.path.splitext(file_name)[0]
    # Gitea 仓库名称规范：只能包含小写字母、数字、连字符(-)和下划线(_)
    # 1. 转换为小写
    repo_name = repo_name_base.lower()
    # 2. 替换空格、点为下划线（保留连字符，因为 Gitea 允许）
    repo_name = repo_name.replace(" ", "_").replace(".", "_")
    # 3. 移除所有非字母数字字符（除了下划线和连字符）
    repo_name = re.sub(r"[^a-z0-9_-]", "_", repo_name)
    # 4. 移除连续的下划线或连字符
    repo_name = re.sub(r"[_-]+", "_", repo_name)
    # 5. 移除开头和结尾的下划线或连字符
    repo_name = repo_name.strip("_-")
    # 6. 如果为空，使用默认名称
    if not repo_name:
        repo_name = "file_" + datetime.now().strftime("%Y%m%d%H%M%S")
    # 7. 限制长度
    if len(repo_name) > 100:
        repo_name = repo_name[:100]
    return repo_name

def upload_file_to_gitea(
    file_path: str, repo_name: str, description: str = "", service: Optional[GiteaService] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    将单个文件上传到 Gitea 并返回仓库的 web_url
    一个文件对应一个仓库

    Args:
        file_path: 要上传的文件路径
        repo_name: 仓库名称
        description: 仓库描述

    Returns:
        成功返回仓库的 web_url，失败返回 None
    """
    try:
        file_path = os.path.abspath(file_path)
        if not os.path.exists(file_path):
            print(f"[FAIL] [upload_file_to_gitea] 文件不存在: {file_path}")
            return None, None

        if not os.path.isfile(file_path):
            print(f"[FAIL] [upload_file_to_gitea] 路径不是文件: {file_path}")
            return None, None

        if service is None:
            service = GiteaService(
                base_url=GITEA_URL,
                username=GITEA_ADMIN_USER,
                password=GITEA_ADMIN_PASSWORD
            )

            if not service.authenticate():
                print("[FAIL] [upload_file_to_gitea] 认证失败")
                return None, None
        # 确保组织存在
        if not service.ensure_org_exists(GITEA_ORG_NAME):
            print(f"[FAIL] [upload_file_to_gitea] 无法确保组织存在: {GITEA_ORG_NAME}")
            return None, None

        # 创建仓库
        repo_info = service.create_repo(
            repo_name=repo_name,
            description=description,
            private=False,
            auto_init=False,
            org_name=GITEA_ORG_NAME,
        )

        if not repo_info:
            print("[FAIL] [upload_file_to_gitea] 无法创建或获取仓库")
            return None, None

        # 获取克隆 URL（带认证信息）
        clone_url = service.get_repo_clone_url(repo_info)
        if not clone_url:
            print("[FAIL] [upload_file_to_gitea] 无法获取仓库克隆 URL")
            return None, None

        print(f"[INFO] [upload_file_to_gitea] 开始上传文件到仓库...")
        print(f"[INFO] [upload_file_to_gitea] 源文件: {file_path}")
        print(f"[INFO] [upload_file_to_gitea] 仓库: {GITEA_ORG_NAME}/{repo_name}")

        # 在文件所在目录下创建一个唯一的临时目录，用于 git 操作
        # 使用时间戳 + UUID 确保唯一性，不删除目录（避免 Windows 删除文件占用问题）
        file_dir = os.path.dirname(file_path)
        tmp_root = os.path.join(
            file_dir,
            f"tmp_gitea_{uuid.uuid4().hex[:8]}",
        )
        os.makedirs(tmp_root, exist_ok=True)
        original_cwd = os.getcwd()

        try:
            # 复制文件到临时目录
            file_name = os.path.basename(file_path)
            dest_file_path = os.path.join(tmp_root, file_name)
            shutil.copy2(file_path, dest_file_path)
            print(
                f"[INFO] [upload_file_to_gitea] 文件已复制到临时目录: {dest_file_path}"
            )

            # 切换到临时目录
            os.chdir(tmp_root)
            # 如果文件类型为 .pptx, .doc, .docx，则用 soffice 转为 pdf（与上传保存时文件名一致）
            ext = os.path.splitext(file_name)[1].lower()
            if ext in [".pptx", ".doc", ".docx"]:
                try:

                    if os.name != "nt":
                        #在windows环境下，执行soffice --version命令，会出现弹窗，提示Press Enter to continue...，导致阻塞
                        # 检查 soffice 是否可用）
                        try:
                            subprocess.run(
                                ["soffice", "--version"],
                                check=True,
                                capture_output=True,
                                timeout=5,
                                stdin=subprocess.DEVNULL   # 避免命令行交互弹窗
                            )
                        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                            print(f"[upload_file_to_gitea] soffice 不可用，跳过 PDF 转换")
                            raise  # 重新抛出异常，让外层 except 处理
                    print(f"[upload_file_to_gitea] 检测到文件类型 {ext}，尝试用 soffice 转为 PDF...")
                    # 构造转换命令
                    convert_cmd = [
                        "soffice",
                        "--headless",
                        "--invisible",
                        "--convert-to", "pdf",
                        "--outdir", tmp_root,
                        file_name
                    ]
                    # 在 Windows 下需使用 cmd 执行 soffice 命令，避免未识别命令问题
                    if os.name == "nt":
                        # 组装完整命令行字符串（带引号）
                        soffice_cmd_str = f'soffice --headless --invisible --convert-to pdf  {file_name}'
                        result = subprocess.run(
                            soffice_cmd_str, shell=True, check=True, capture_output=True, text=True
                        )
                    else:
                        # 非 Windows 直接调用
                        result = subprocess.run(
                            convert_cmd, check=True, capture_output=True, text=True
                        )
                    print(f"[upload_file_to_gitea] soffice 输出: {result.stdout.strip()} {result.stderr.strip()}")
                    # 转换后的pdf文件名
                    pdf_file_name = os.path.splitext(file_name)[0] + ".pdf"
                    pdf_file_path = os.path.join(tmp_root, pdf_file_name)
                    if os.path.isfile(pdf_file_path):
                        print(f"[upload_file_to_gitea] PDF 文件已生成: {pdf_file_name}")
                        # 如果生成了 PDF，则只上传 PDF 文件，删除原来的 office 文件
                        os.remove(dest_file_path)
                        dest_file_path = pdf_file_path
                        file_name = pdf_file_name
                    else:
                        print(f"[upload_file_to_gitea] PDF 文件未生成, 继续上传原文件")
                except Exception as e:
                    print(f"[upload_file_to_gitea] 转换PDF出错: {e}，将继续上传原文件")

            # 初始化 git 仓库
            print("[INFO] [upload_file_to_gitea] 初始化 Git 仓库...")
            subprocess.run(["git", "init"], check=True, capture_output=True)

            # 配置 git 用户信息（避免提交时缺少用户信息）
            subprocess.run(
                ["git", "config", "user.name", service.username], capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", f"{service.username}@gitea.local"],
                capture_output=True,
            )

            # 添加文件
            print("[INFO] [upload_file_to_gitea] 添加文件到 Git...")
            subprocess.run(["git", "add", file_name], check=True, capture_output=True)

            # 提交
            print("[INFO] [upload_file_to_gitea] 提交文件...")
            commit_message = f"Upload file: {file_name}"
            subprocess.run(
                ["git", "commit", "-m", commit_message], check=True, capture_output=True
            )

            # 添加远程仓库
            print("[INFO] [upload_file_to_gitea] 配置远程仓库...")
            subprocess.run(["git", "remote", "add", "origin", clone_url], check=True)

            # 推送代码
            print("[INFO] [upload_file_to_gitea] 推送代码到 Gitea...")
            branch_name = "main"
            # 尝试推送到 main 分支，如果失败则尝试 master
            try:
                subprocess.run(
                    ["git", "push", "-u", "origin", "HEAD:main", "--force"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                print("[INFO] [upload_file_to_gitea] 代码已推送到 main 分支")
            except subprocess.CalledProcessError:
                try:
                    subprocess.run(
                        ["git", "push", "-u", "origin", "HEAD:master", "--force"],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    print("[INFO] [upload_file_to_gitea] 代码已推送到 master 分支")
                    branch_name = "master"
                except subprocess.CalledProcessError as e:
                    print(
                        f"[FAIL] [upload_file_to_gitea] 推送失败: {e.stderr if e.stderr else e}"
                    )
                    return None, None
            web_url = repo_info.get("html_url", "")
            print(f"[OK] [upload_file_to_gitea] 文件已成功上传到 Gitea 仓库")
            print(f"[INFO] [upload_file_to_gitea] 仓库 Web URL: {web_url}")
            return web_url, branch_name

        except subprocess.CalledProcessError as e:
            print(
                f"[FAIL] [upload_file_to_gitea] Git 操作失败: {e.stderr.decode() if e.stderr else str(e)}"
            )
            try:
                os.chdir(original_cwd)
            except:
                pass
            return None, None
        except Exception as e:
            print(f"[FAIL] [upload_file_to_gitea] 上传过程异常: {e}")
            try:
                os.chdir(original_cwd)
            except:
                pass
            return None, None
        finally:
            # Git push 成功，恢复原始工作目录，并删除相关文件夹
            os.chdir(original_cwd)

            # 等待一下，确保 Git 进程完全结束
            time.sleep(0.5)

            # 尝试删除临时目录
            if os.path.exists(tmp_root):
                try:
                    # Windows 删除辅助函数：使文件可写
                    def make_writable(func, path, exc_info):
                        """使文件可写，用于处理 Windows 权限问题"""
                        if os.path.exists(path):
                            try:
                                os.chmod(path, stat.S_IWRITE)
                                func(path)
                            except Exception:
                                pass

                    # 尝试删除临时目录
                    shutil.rmtree(tmp_root, onerror=make_writable)
                    print(f"[INFO] [upload_file_to_gitea] 临时目录已清理: {tmp_root}")
                except Exception as e:
                    # Windows 删除失败很常见（文件被占用），记录警告但不影响主流程
                    print(
                        f"[WARN] [upload_file_to_gitea] 临时目录删除失败（Windows 常见问题）: {tmp_root}, "
                        f"错误: {e}。目录将在后续手动清理或系统重启时自动清理。"
                    )

    except Exception as e:
        print(f"[FAIL] [upload_file_to_gitea] 上传失败: {e}")
        return None, None



def upload_folder_to_gitea(
    folder_path: str,
    repo_name: Optional[str] = None,
    org_name: Optional[str] = None,
    description: str = "",
    service: Optional[GiteaService] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    将文件夹内容上传到 Gitea 仓库

    Args:
        folder_path: 要上传的文件夹路径
        repo_name: 仓库名称，如果不提供则使用文件夹名称
        org_name: 组织名称，如果不提供则使用默认组织
        description: 仓库描述
        service: GiteaService 实例，如果不提供则创建新的

    Returns:
        成功返回 True，失败返回 False
    """
    folder_path = os.path.abspath(folder_path)
    if not os.path.exists(folder_path):
        print(f"[FAIL] 文件夹不存在: {folder_path}")
        return None, None

    if not os.path.isdir(folder_path):
        print(f"[FAIL] 路径不是文件夹: {folder_path}")
        return None, None

    # 确定仓库名称
    if not repo_name:
        repo_name = os.path.basename(folder_path.rstrip('/\\'))

    # 初始化或使用已有的 Gitea 服务
    if service is None:
        service = GiteaService(
            base_url=GITEA_URL,
            username=GITEA_ADMIN_USER,
            password=GITEA_ADMIN_PASSWORD
        )

        # 认证
        if not service.authenticate():
            print("[FAIL] 认证失败")
            return None, None

    # 确定组织名称
    target_org_name = org_name or GITEA_ORG_NAME

    # 确保组织存在
    if target_org_name:
        if not service.ensure_org_exists(target_org_name):
            print(f"[FAIL] 无法确保组织存在: {target_org_name}")
            return None, None

    # 创建仓库
    repo_info = service.create_repo(
        repo_name=repo_name,
        description=description,
        private=False,
        auto_init=False,
        org_name=target_org_name
    )

    if not repo_info:
        print("[FAIL] 无法创建或获取仓库")
        return None, None

    # 获取克隆 URL（带认证信息）
    clone_url = service.get_repo_clone_url(repo_info)
    if not clone_url:
        print("[FAIL] 无法获取仓库克隆 URL")
        return None, None

    print(f"[INFO] 开始上传文件夹内容到仓库...")
    print(f"      源文件夹: {folder_path}")
    print(f"      仓库: {target_org_name}/{repo_name}")

    try:
        # 切换到文件夹目录
        original_cwd = os.getcwd()
        os.chdir(folder_path)

        # 检查是否已经是 git 仓库
        if os.path.exists('.git'):
            print("[INFO] 检测到已有 .git 目录，将使用现有仓库")
        else:
            # 初始化 git 仓库
            print("[INFO] 初始化 Git 仓库...")
            subprocess.run(['git', 'init'], check=True, capture_output=True)

        # 添加所有文件
        print("[INFO] 添加文件到 Git...")
        subprocess.run(['git', 'add', '.'], check=True, capture_output=True)

        # 检查是否有变更
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True,
            text=True
        )
        if not result.stdout.strip():
            print("[INFO] 没有文件变更，跳过提交")
        else:
            # 提交
            print("[INFO] 提交文件...")
            subprocess.run(
                ['git', 'commit', '-m', 'Initial commit: upload from folder'],
                check=True,
                capture_output=True
            )

        # 添加远程仓库（如果已存在则先删除）
        print("[INFO] 配置远程仓库...")
        subprocess.run(['git', 'remote', 'remove', 'origin'], capture_output=True)
        subprocess.run(['git', 'remote', 'add', 'origin', clone_url], check=True)

        # 推送代码
        print("[INFO] 推送代码到 Gitea...")
        branch_name = "main"
        # 尝试推送到 main 分支，如果失败则尝试 master
        try:
            subprocess.run(
                ['git', 'push', '-u', 'origin', 'HEAD:main', '--force'],
                check=True,
                capture_output=True,
                text=True
            )
            print("[OK] 代码已推送到 main 分支")
        except subprocess.CalledProcessError:
            try:
                subprocess.run(
                    ['git', 'push', '-u', 'origin', 'HEAD:master', '--force'],
                    check=True,
                    capture_output=True,
                    text=True
                )
                print("[OK] 代码已推送到 master 分支")
                branch_name = "master"
            except subprocess.CalledProcessError as e:
                print(f"[FAIL] 推送失败: {e.stderr if e.stderr else e}")
                return None, None

        # 恢复原始工作目录
        os.chdir(original_cwd)

        print(f"[OK] 文件夹内容已成功上传到 Gitea 仓库")
        if not repo_info.get("html_url"):
            return None, None
        return repo_info.get("html_url"), branch_name

    except subprocess.CalledProcessError as e:
        print(f"[FAIL] Git 操作失败: {e.stderr.decode() if e.stderr else str(e)}")
        try:
            os.chdir(original_cwd)
        except:
            pass
        return None, None
    except Exception as e:
        print(f"[FAIL] 上传过程异常: {e}")
        try:
            os.chdir(original_cwd)
        except:
            pass
        return None, None

def update_repo_url(repo_url: str, software_name: str, branch_name: str, all_files: List[str]) -> Tuple[List[str], str]:
    """
    更新仓库的 URL 到 Neo4j 图数据库中的相关节点

    Args:
        repo_url: 仓库的 URL（html_url）
        software_name: 软件名称，用于查询对应的节点

    Returns:
        成功返回 MitreAttackCodeSoftwareCodeChunk 节点的 elementId 列表，失败返回空列表
    """
    try:
        from database_helper.neo4j_helper import Neo4jHelper

        # 初始化 Neo4j 连接
        neo4j_helper = Neo4jHelper()
        # 检查是否有文件名重复的情况
        duplicate_query = """
        MATCH (software:MitreAttackCodeSoftware {name: $software_name})
              -[:CODE_SOFTWARE_HAS_CODE_SOFTWARE_FILE]->
              (file:MitreAttackCodeSoftwareFile)
        WITH file.name AS file_name, COUNT(file) AS file_count
        WHERE file_count > 1
        WITH COUNT(*) AS duplicate_count
        RETURN duplicate_count > 0 AS has_duplicates, duplicate_count AS duplicate_file_count
        """
        with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as duplicate_session:
            duplicate_result = duplicate_session.run(duplicate_query, software_name=software_name)
            duplicate_info = duplicate_result.single()
            if duplicate_info and duplicate_info["has_duplicates"]:
                print(f"[FAIL] 存在文件名重复情况, 共有 {duplicate_info['duplicate_file_count']} 个重复文件名。")
                return [], "文件名重复"


        code_chunk_element_ids = []

        # 查询软件节点及其关联的文件和代码块
        query = """
        MATCH (software:MitreAttackCodeSoftware)
        WHERE software.name = $software_name
        OPTIONAL MATCH (software)-[r1:CODE_SOFTWARE_HAS_CODE_SOFTWARE_FILE]->(file:MitreAttackCodeSoftwareFile)
        OPTIONAL MATCH (file)-[r3:CODE_SOFTWARE_FILE_HAS_CODE_SOFTWARE_CODE_CHUNK]->(code:MitreAttackCodeSoftwareCodeChunk)
        RETURN software, file, code
        """

        with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as session:
            result = session.run(query, software_name=software_name)

            # 收集所有需要更新的节点
            software_node = None
            file_nodes = []
            code_nodes = []

            for record in result:
                # 处理 software 节点
                if record.get("software"):
                    software_node = record["software"]

                # 处理 file 节点
                if record.get("file"):
                    file_nodes.append(record["file"])

                # 处理 code 节点
                if record.get("code"):
                    code_nodes.append(record["code"])

            #如果当前software_node依旧为空，那么说明当前项目没有经过知识库存储
            if not software_node:
                print(f"[FAIL] 当前项目{software_name}没有经过知识库存储,跳过更新")
                return [],""
            # 更新 software 节点的 repo_url
            if software_node:
                session.run(
                    "MATCH (n:MitreAttackCodeSoftware) WHERE elementId(n) = $element_id AND n.repo_url IS NULL SET n.repo_url = $repo_url",
                    element_id=software_node.element_id, repo_url=repo_url
                )
                print(f"[INFO] 更新 Software 节点 repo_url: {software_node.element_id}")

            # 去重 file_nodes
            seen_file_elements = set()
            unique_file_nodes = []
            for file_node in file_nodes:
                if file_node.element_id not in seen_file_elements:
                    seen_file_elements.add(file_node.element_id)
                    unique_file_nodes.append(file_node)

            # 更新 file 节点的 repo_url
            for file_node in unique_file_nodes:
                #根据all_files中的相对目录名，去查找当前file_node的相对目录
                namefile = file_node.get("name")
                matching_path = None
                for rel_path in all_files:
                    if os.path.basename(rel_path) == namefile:
                        matching_path = rel_path
                        break
                if matching_path:
                    file_relative_path = pathlib.Path(matching_path).as_posix()
                    file_repo_url = f"{repo_url}/src/branch/{branch_name}/{file_relative_path}"
                    session.run(
                        "MATCH (n:MitreAttackCodeSoftwareFile) WHERE elementId(n) = $element_id AND n.repo_url IS NULL SET n.repo_url = $repo_url",
                        element_id=file_node.element_id, repo_url=file_repo_url
                    )
                    print(f"[INFO] 更新 File 节点 repo_url: {file_node.element_id}")
                else:
                    print(f"[WARN] 未找到文件 {namefile} 在 all_files 中的匹配路径")

            # 去重 code_nodes 并收集 element_id
            seen_code_elements = set()
            unique_code_nodes = []
            for code_node in code_nodes:
                if code_node.element_id not in seen_code_elements:
                    seen_code_elements.add(code_node.element_id)
                    unique_code_nodes.append(code_node)
                    code_chunk_element_ids.append(code_node.element_id)

            # 更新 code 节点的 repo_url
            for code_node in unique_code_nodes:
                session.run(
                    "MATCH (n:MitreAttackCodeSoftwareCodeChunk) WHERE elementId(n) = $element_id AND n.repo_url IS NULL SET n.repo_url = $repo_url",
                    element_id=code_node.element_id, repo_url=file_repo_url
                )
                print(f"[INFO] 更新 CodeChunk 节点 repo_url: {code_node.element_id}")

            print(f"[OK] 成功更新 {len(unique_file_nodes)} 个 File 节点和 {len(unique_code_nodes)} 个 CodeChunk 节点的 repo_url")
            return code_chunk_element_ids, ""

    except Exception as e:
        print(f"[FAIL] 更新仓库 URL 失败: {e}")
        return [],""

def add_milvus_from_code_chunk(code_chunk_element_ids: List[str], softname: str, repo_url: str) -> bool:
    """
    根据 Neo4j 的 CodeChunk element_id 更新 Milvus 中对应记录的 soft_name 和 url

    Args:
        code_chunk_element_ids: Neo4j 中 MitreAttackCodeSoftwareCodeChunk 节点的 element_id 列表
        softname: 软件名称,将更新到 Milvus 的 soft_name 字段
        repo_url: 仓库 URL,将更新到 Milvus 的 url 字段

    Returns:
        成功返回 True,失败返回 False
    """
    if not milvus_connected:
        print("[FAIL] Milvus 未连接,无法更新数据")
        return False

    if not code_chunk_element_ids:
        print("[WARN] 没有提供 code_chunk_element_ids")
        return False

    try:
        # 获取 collection
        if not utility.has_collection(MILVUS_COLLECTION):
            print(f"[FAIL] Collection {MILVUS_COLLECTION} 不存在")
            return False

        collection = Collection(MILVUS_COLLECTION)
        collection.load()

        print(f"[INFO] 开始为 {len(code_chunk_element_ids)} 个代码块更新 Milvus 记录")
        print(f"       soft_name: {softname}")
        print(f"       repo_url: {repo_url}")

        # 步骤1: 只查询 neo4j_id 来验证记录存在
        try:
            expr_ids = ", ".join([f'"{eid}"' for eid in code_chunk_element_ids])
            result = collection.query(
                expr=f"neo4j_id in [{expr_ids}]",
                output_fields=["*"]
            )

            if not result:
                print(f"[WARN] 在 Milvus 中没有找到匹配的记录,跳过更新")
                return False

            matched_ids = [item["neo4j_id"] for item in result]
            print(f"[INFO] 在 Milvus 中找到 {len(matched_ids)} 条匹配记录")

        except Exception as e:
            print(f"[FAIL] 查询 Milvus 失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        # 步骤3: 批量更新 - 只修改 soft_name 和 url,其他字段保持原值
        success_count = 0
        BATCH_SIZE = 100

        for i in range(0, len(result), BATCH_SIZE):
            batch_data = result[i:i + BATCH_SIZE]

            # 提取所有字段,只修改 soft_name 和 url
            batch_neo4j_ids = [item["neo4j_id"] for item in batch_data]
            batch_code_data = [item["code_data"] for item in batch_data]
            batch_descriptions = [item["description"] for item in batch_data]
            batch_embeddings = [item["code__embedding"] for item in batch_data]
            batch_soft_names = [softname] * len(batch_data)  # 更新为新值
            batch_urls = [repo_url] * len(batch_data)  # 更新为新值

            try:
                # upsert 必须提供所有字段,但我们只修改 soft_name 和 url
                collection.upsert(
                    data=[
                        batch_neo4j_ids,      # 主键
                        batch_code_data,      # 保持原值
                        batch_descriptions,   # 保持原值
                        batch_embeddings,     # 保持原值
                        batch_soft_names,     # ✨ 更新
                        batch_urls,           # ✨ 更新
                    ]
                )
                success_count += len(batch_neo4j_ids)
                print(f"[OK] 已更新 {success_count}/{len(result)} 条记录")

            except Exception as e:
                print(f"[FAIL] 批量更新失败 (批次 {i//BATCH_SIZE + 1}): {e}")
                continue

        print(f"[OK] Milvus 更新完成,成功更新 {success_count} 条记录")
        return success_count > 0

    except Exception as e:
        print(f"[FAIL] 更新 Milvus 时发生异常: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_repo_url_for_file(repo_url: str, document_name: str) -> List[str]:
    """
    更新仓库的 URL 到 Neo4j 图数据库中的文件相关节点（ArticleDocument 和 ArticleChunk）

    Args:
        repo_url: 仓库的 URL（html_url）
        document_name: 文档名称（title），用于查询对应的节点

    Returns:
        成功返回 MitreAttackArticleChunk 节点的 elementId 列表，失败返回空列表
    """
    try:
        from database_helper.neo4j_helper import Neo4jHelper

        # 初始化 Neo4j 连接
        neo4j_helper = Neo4jHelper()
        article_chunk_element_ids = []

        # 查询文档节点及其关联的文章块
        query = """
        MATCH (document:MitreAttackArticleDocument)
        WHERE document.title = $document_name
        OPTIONAL MATCH (document)-[r1:DOCUMENT_HAS_CHUNK]->(chunk:MitreAttackArticleChunk)
        RETURN document, chunk
        """

        with neo4j_helper.neo4j_driver.session(**neo4j_helper.session_kwargs) as session:
            result = session.run(query, document_name=document_name)

            # 收集所有需要更新的节点
            document_node = None
            chunk_nodes = []

            for record in result:
                # 处理 document 节点
                if record.get("document"):
                    document_node = record["document"]

                # 处理 chunk 节点
                if record.get("chunk"):
                    chunk_nodes.append(record["chunk"])
            

            #如果当前document_node依旧为空，那么说明当前项目没有经过知识库存储
            if not document_node:
                print(f"[FAIL] 当前文件{document_name}没有经过知识库存储,跳过更新")
                return []

            # 更新 document 节点的 repo_url
            if document_node:
                session.run(
                    "MATCH (n:MitreAttackArticleDocument) WHERE elementId(n) = $element_id AND n.repo_url IS NULL SET n.repo_url = $repo_url",
                    element_id=document_node.element_id, repo_url=repo_url
                )
                print(f"[INFO] 更新 ArticleDocument 节点 repo_url: {document_node.element_id}")

            # 去重 chunk_nodes 并收集 element_id
            seen_chunk_elements = set()
            unique_chunk_nodes = []
            for chunk_node in chunk_nodes:
                if chunk_node.element_id not in seen_chunk_elements:
                    seen_chunk_elements.add(chunk_node.element_id)
                    unique_chunk_nodes.append(chunk_node)
                    article_chunk_element_ids.append(chunk_node.element_id)

            # 更新 chunk 节点的 repo_url
            for chunk_node in unique_chunk_nodes:
                session.run(
                    "MATCH (n:MitreAttackArticleChunk) WHERE elementId(n) = $element_id AND n.repo_url IS NULL SET n.repo_url = $repo_url",
                    element_id=chunk_node.element_id, repo_url=repo_url
                )
                print(f"[INFO] 更新 ArticleChunk 节点 repo_url: {chunk_node.element_id}")

            print(f"[OK] 成功更新 {len(unique_chunk_nodes)} 个 ArticleChunk 节点的 repo_url")
            return article_chunk_element_ids

    except Exception as e:
        print(f"[FAIL] 更新文件仓库 URL 失败: {e}")
        return []


def add_milvus_from_article_chunk(article_chunk_element_ids: List[str], softname: str, repo_url: str) -> bool:
    """
    根据 Neo4j 的 ArticleChunk element_id 更新 Milvus 中对应记录的 soft_name 和 url

    Args:
        article_chunk_element_ids: Neo4j 中 MitreAttackArticleChunk 节点的 element_id 列表
        softname: 软件名称,将更新到 Milvus 的 soft_name 字段
        repo_url: 仓库 URL,将更新到 Milvus 的 url 字段

    Returns:
        成功返回 True,失败返回 False
    """
    if not milvus_connected:
        print("[FAIL] Milvus 未连接,无法更新数据")
        return False

    if not article_chunk_element_ids:
        print("[WARN] 没有提供 article_chunk_element_ids")
        return False

    try:
        # 获取 collection
        if not utility.has_collection(MILVUS_COLLECTION):
            print(f"[FAIL] Collection {MILVUS_COLLECTION} 不存在")
            return False

        collection = Collection(MILVUS_COLLECTION)
        collection.load()

        print(f"[INFO] 开始为 {len(article_chunk_element_ids)} 个文章块更新 Milvus 记录")
        print(f"       soft_name: {softname}")
        print(f"       repo_url: {repo_url}")

        # 步骤1: 只查询 neo4j_id 来验证记录存在
        try:
            expr_ids = ", ".join([f'"{eid}"' for eid in article_chunk_element_ids])
            result = collection.query(
                expr=f"neo4j_id in [{expr_ids}]",
                output_fields=["*"]
            )

            if not result:
                print(f"[WARN] 在 Milvus 中没有找到匹配的记录,跳过更新")
                return False

            matched_ids = [item["neo4j_id"] for item in result]
            print(f"[INFO] 在 Milvus 中找到 {len(matched_ids)} 条匹配记录")

        except Exception as e:
            print(f"[FAIL] 查询 Milvus 失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        # 步骤2: 批量更新 - 只修改 soft_name 和 url,其他字段保持原值
        success_count = 0
        BATCH_SIZE = 100

        for i in range(0, len(result), BATCH_SIZE):
            batch_data = result[i:i + BATCH_SIZE]

            # 提取所有字段,只修改 soft_name 和 url
            batch_neo4j_ids = [item["neo4j_id"] for item in batch_data]
            batch_code_data = [item["code_data"] for item in batch_data]
            batch_descriptions = [item["description"] for item in batch_data]
            batch_embeddings = [item["code__embedding"] for item in batch_data]
            batch_soft_names = [softname] * len(batch_data)  # 更新为新值
            batch_urls = [repo_url] * len(batch_data)  # 更新为新值

            try:
                # upsert 必须提供所有字段,但我们只修改 soft_name 和 url
                collection.upsert(
                    data=[
                        batch_neo4j_ids,      # 主键
                        batch_code_data,      # 保持原值
                        batch_descriptions,   # 保持原值
                        batch_embeddings,     # 保持原值
                        batch_soft_names,     # ✨ 更新
                        batch_urls,           # ✨ 更新
                    ]
                )
                success_count += len(batch_neo4j_ids)
                print(f"[OK] 已更新 {success_count}/{len(result)} 条记录")

            except Exception as e:
                print(f"[FAIL] 批量更新失败 (批次 {i//BATCH_SIZE + 1}): {e}")
                continue

        print(f"[OK] Milvus 更新完成,成功更新 {success_count} 条记录")
        return success_count > 0

    except Exception as e:
        print(f"[FAIL] 更新 Milvus 时发生异常: {e}")
        import traceback
        traceback.print_exc()
        return False


def batch_upload_folders_code(
    base_path: str,
    org_name: Optional[str] = None,
    description_template: str = "项目批量上传"
):
    """
    批量上传代码文件夹到 Gitea（处理 MitreAttackCodeSoftware 相关节点）

    Args:
        base_path: 基础路径，包含所有要上传的项目文件夹
        org_name: 组织名称，如果不提供则使用默认组织
        description_template: 仓库描述模板

    Returns:
        返回字典，键为文件夹路径，值为是否成功
    """
    # 初始化 Gitea 服务（复用连接）
    service = GiteaService(
        base_url=GITEA_URL,
        username=GITEA_ADMIN_USER,
        password=GITEA_ADMIN_PASSWORD
    )

    # 认证
    if not service.authenticate():
        print("[FAIL] 认证失败")
        return {}

    # 获取所有子文件夹
    subfolders = get_subfolders(base_path)

    if not subfolders:
        print(f"[INFO] 在 {base_path} 中没有找到任何子文件夹")
        return {}

    print(f"[INFO] 找到 {len(subfolders)} 个子文件夹")
    print("=" * 80)

    # 批量上传
    results = {}
    success_count = 0
    fail_count = 0

    def _walk_directory(directory: Path) -> List[Path]:
            """遍历目录，返回所有文件路径"""
            files = []
            
            for item in directory.rglob('*'):
                if item.is_file():
                    # 检查是否在忽略的目录中
                    if any(ignore_dir in item.parts for ignore_dir in IGNORE_DIRS):
                        continue
                    # 检查是否是忽略的文件
                    if item.name in IGNORE_FILES:
                        continue
                    files.append(item)
            
            return files

    def _is_code_file(file_path: Path):
        """判断是否为代码文件"""
        return file_path.suffix.lower() in CODE_EXTENSIONS
    def _is_valid_file(file_path: Path):
        """判断文件是否有效（大小限制等）"""
        try:
            file_size = file_path.stat().st_size
            return file_size <= max_file_size
        except OSError:
            return False

    duplicate_repos = []
    for i, folder_path in enumerate(subfolders, 1):
        folder_name = os.path.basename(folder_path)
        print(f"\n[{i}/{len(subfolders)}] 正在处理: {folder_name}")
        print("-" * 80)
        all_files = []
        for file_path in _walk_directory(Path(folder_path)):
            if _is_code_file(file_path) and _is_valid_file(file_path):
                file_relative_path = os.path.relpath(file_path, start=folder_path)
                all_files.append(file_relative_path)
        print(f"[INFO] {folder_name} 包含 {len(all_files)} 个文件:")

        description = f"{description_template} - {folder_name}"
        repo_url, branch_name = upload_folder_to_gitea(
            folder_path=folder_path,
            repo_name=folder_name,
            org_name=org_name,
            description=description,
            service=service
        )
        if not repo_url or not branch_name:
            print(f"[FAIL] 上传失败: {folder_name}")
            continue
        code_chunk_element_ids, msg = update_repo_url(repo_url, folder_name, branch_name, all_files)
        if msg == "文件名重复":
            duplicate_repos.append(folder_name)
            continue
        if not code_chunk_element_ids:
            print(f"[FAIL] 更新仓库 URL 失败: {folder_name}")
            continue

        # 更新 Milvus 中的 soft_name 和 url
        print(f"[INFO] 开始更新 Milvus 记录...")
        milvus_updated = add_milvus_from_code_chunk(
            code_chunk_element_ids=code_chunk_element_ids,
            softname=folder_name,
            repo_url=repo_url
        )
        if not milvus_updated:
            print(f"[WARN] Milvus 更新失败或没有匹配记录: {folder_name}")
            continue
        else:
            print(f"[OK] Milvus 更新成功: {folder_name}")

        results[folder_path] = repo_url
        if repo_url:
            success_count += 1
        else:
            fail_count += 1

        print(f"[{'OK' if repo_url else 'FAIL'}] {folder_name}: {'成功' if repo_url else '失败'}")
    if duplicate_repos:
        print(f"[FAIL] 存在项目中的文件名重复情况, 共有 {len(duplicate_repos)} 个重复项目。这些项目不适用于批量上传，需要重新被知识库进行处理")
        print(f"重复项目名: {duplicate_repos}")
        return {}

    # 打印总结
    print("\n" + "=" * 80)
    print("批量上传完成！")
    print(f"总计: {len(subfolders)} 个文件夹")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")



def batch_upload_folders_file(
    base_path: str,
    org_name: Optional[str] = None,
    description_template: str = "文件批量上传"
):
    """
    批量上传文件文件夹到 Gitea（处理 MitreAttackArticleDocument 相关节点）

    说明：
    - 此函数专门处理文件类项目（如 PDF 文档），对应 Neo4j 中的 ArticleDocument 节点
    - 文件夹名称即为文档的 title，用于匹配 Neo4j 中的 MitreAttackArticleDocument.title
    - 例如：文件夹 "APP漏洞挖掘之某下载量超101万的APP有几个漏洞可以GetShell？.pdf"
            对应 ArticleDocument.title 为 "APP漏洞挖掘之某下载量超101万的APP有几个漏洞可以GetShell？"

    Args:
        base_path: 基础路径，包含所有要上传的文件文件夹（如 PDF 文档文件夹）
        org_name: 组织名称，如果不提供则使用默认组织
        description_template: 仓库描述模板

    Returns:
        返回字典，键为文件夹路径，值为是否成功
    """
    # 初始化 Gitea 服务（复用连接）
    service = GiteaService(
        base_url=GITEA_URL,
        username=GITEA_ADMIN_USER,
        password=GITEA_ADMIN_PASSWORD
    )

    # 认证
    if not service.authenticate():
        print("[FAIL] 认证失败")
        return {}

    # 获取当前目录下所有条目（文件和文件夹）
    all_items = os.listdir(base_path)

    # 筛选出文件（排除文件夹）
    files = [os.path.join(base_path, item) for item in all_items if os.path.isfile(os.path.join(base_path, item))]

    if not files:
        print(f"[INFO] 在 {base_path} 中没有找到任何子文件")
        return {}

    print(f"[INFO] 找到 {len(files)} 个文件")
    print("=" * 80)

    # 批量上传
    results = {}
    success_count = 0
    fail_count = 0

    for i, file_path in enumerate(files, 1):
        # 获取文件夹名称（可能包含 .pdf 等扩展名）
        file_name = os.path.basename(file_path)

        # 提取文档标题（去除文件扩展名，如 .pdf）
        # 例如：APP漏洞挖掘之某下载量超101万的APP有几个漏洞可以GetShell？.pdf
        #      -> APP漏洞挖掘之某下载量超101万的APP有几个漏洞可以GetShell？
        document_title = file_name
        if '.' in file_name:
            # 保留主文件名，去掉扩展名
            document_title = file_name.rsplit('.', 1)[0]

        print(f"\n[{i}/{len(files)}] 正在处理文件: {file_name}")
        print(f"[INFO] 文档标题: {document_title}")
        print("-" * 80)

        repo_name = handle_reponame(document_title)
        print(f"[INFO] 仓库名称: {repo_name}")

        # 上传文件文件夹到 Gitea（使用文件夹名称作为仓库名）
        description = f"{description_template} - {document_title}"
        repo_url, branch_name = upload_file_to_gitea(
            file_path=file_path,
            repo_name=repo_name,  # 使用原始文件夹名作为仓库名
            description=description,
            service=service
        )
        if not repo_url or not branch_name:
            print(f"[FAIL] 上传失败: {file_name}")
            continue
        
        file_name_show = file_name
        ext = os.path.splitext(file_name)[1].lower()
        if ext in [".pptx", ".doc", ".docx"]:
            file_name_show = os.path.splitext(file_name)[0] + ".pdf"
        file_repo_url = f"{repo_url}/src/branch/{branch_name}/{file_name_show}"

        # 更新 Neo4j 中 ArticleDocument 和 ArticleChunk 节点的 repo_url
        # 注意：这里使用 document_title（去掉扩展名）来匹配 ArticleDocument.title
        article_chunk_element_ids = update_repo_url_for_file(file_repo_url, document_title)
        if not article_chunk_element_ids:
            print(f"[FAIL] 更新文件仓库 URL 失败: {file_name}")
            print(f"[WARN] 可能原因：Neo4j 中未找到 title='{document_title}' 的 ArticleDocument 节点")
            continue

        # 更新 Milvus 中的 soft_name 和 url
        print(f"[INFO] 开始更新 Milvus 记录...")
        milvus_updated = add_milvus_from_article_chunk(
            article_chunk_element_ids=article_chunk_element_ids,
            softname=document_title,  # 使用文档标题作为 soft_name
            repo_url=file_repo_url
        )
        if not milvus_updated:
            print(f"[WARN] Milvus 更新失败或没有匹配记录: {file_name}")
            continue
        else:
            print(f"[OK] Milvus 更新成功: {file_name}")

        results[file_path] = repo_url
        if repo_url:
            success_count += 1
        else:
            fail_count += 1

        print(f"[{'OK' if repo_url else 'FAIL'}] {file_name}: {'成功' if repo_url else '失败'}")

    # 打印总结
    print("\n" + "=" * 80)
    print("文件批量上传完成！")
    print(f"总计: {len(files)} 个文件文件夹")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")


def main():
    #pyton batch_upload_projects.py /TestProject
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python batch_upload_projects.py <base_path> [--org <org_name>] [--desc <description>]")
        print("\n示例:")
        print("  python batch_upload_projects.py .")
        print("  python batch_upload_projects.py /path/to/projects")
        print("  python batch_upload_projects.py . --org red_team_rag --desc '批量上传项目'")
        sys.exit(1)

    base_path = sys.argv[1]
    org_name = None
    description_template = "项目批量上传"

    # 解析参数
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--org' and i + 1 < len(sys.argv):
            org_name = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--desc' and i + 1 < len(sys.argv):
            description_template = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    # 检查路径是否存在
    if not os.path.exists(base_path):
        print(f"[FAIL] 路径不存在: {base_path}")
        sys.exit(1)

    if not os.path.isdir(base_path):
        print(f"[FAIL] 路径不是文件夹: {base_path}")
        sys.exit(1)

    print(f"批量上传文件夹到 Gitea")
    print(f"基础路径: {os.path.abspath(base_path)}")
    if org_name:
        print(f"组织名称: {org_name}")
    print(f"描述模板: {description_template}")
    print("=" * 80)
    import tarfile
    import glob

    codes_path = os.path.join(base_path, "codes")

    # 解压 codes 文件夹下所有 .tar.gz 压缩包
    if os.path.exists(codes_path) and os.path.isdir(codes_path):
        tar_files = glob.glob(os.path.join(codes_path, "*.tar.gz"))
        for tar_file in tar_files:
            try:
                print(f"[INFO] 解压: {tar_file}")
                with tarfile.open(tar_file, "r:gz") as tar:
                    tar.extractall(path=codes_path)
                print(f"[OK] 解压完成: {os.path.basename(tar_file)}")
            except Exception as e:
                print(f"[FAIL] 解压失败: {os.path.basename(tar_file)}，原因: {e}")
        # 删除所有压缩包文件
        for tar_file in tar_files:
            try:
                os.remove(tar_file)
                print(f"[INFO] 已删除压缩包: {os.path.basename(tar_file)}")
            except Exception as e:
                print(f"[FAIL] 删除压缩包失败: {os.path.basename(tar_file)}，原因: {e}")
    else:
        print(f"[WARN] 未找到 codes 文件夹: {codes_path}")

    batch_upload_folders_file(
        base_path=os.path.join(base_path, "files"),
        org_name=org_name,
        description_template=description_template
    )
    batch_upload_folders_code(
            base_path=os.path.join(base_path, "codes"),
            org_name=org_name,
            description_template=description_template
        )


if __name__ == "__main__":
    main()