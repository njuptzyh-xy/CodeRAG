"""
Gitea 服务辅助模块

提供 Gitea API 交互功能，包括认证、组织管理、仓库创建和代码上传。
"""

from datetime import datetime
import os
import subprocess
import tempfile
import shutil
import uuid
import time
import stat
from typing import Optional, Dict, Any, Tuple
from urllib.parse import quote
from red_kbs_analyzer.run_logs.logger import logger
import requests
from setting import GITEA_URL, GITEA_ORG_NAME, GITEA_ADMIN_PASSWORD, GITEA_ADMIN_USER


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
        self.base_url = base_url.rstrip("/")
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
                "name": "api_token_upload_code",
                "scopes": ["write:repository", "read:repository", "write:organization"],
            }

            response = self.session.post(
                auth_url,
                json=auth_data,
                auth=(self.username, self.password),
                timeout=10,
            )

            if response.status_code == 201:
                self.token = response.json().get("sha1")
                logger.info(f"[Gitea] 认证成功，获取到 token")
                return True
            elif response.status_code == 200:
                logger.info(f"[Gitea] Token 可能已存在，使用 Basic Auth")
                self.token = None
                return True
            else:
                logger.info(
                    f"[Gitea] Token 创建失败，尝试使用 Basic Auth: HTTP {response.status_code}"
                )
                self.token = None
                return True

        except Exception as exc:
            logger.warning(f"[Gitea] 认证异常，将使用 Basic Auth: {exc}")
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
                    get_url, headers=self._get_headers(), timeout=10
                )
            else:
                response = self.session.get(get_url, auth=self._get_auth(), timeout=10)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                logger.warning(f"[Gitea] 获取组织信息失败: HTTP {response.status_code}")
                return None

        except Exception as exc:
            logger.warning(f"[Gitea] 获取组织信息异常: {exc}")
            return None

    def ensure_org_exists(self, org_name: str) -> bool:
        """确保组织存在，如果不存在则创建"""
        org_info = self.get_org(org_name)
        if org_info:
            logger.info(f"[Gitea] 组织已存在: {org_name}")
            return True

        logger.info(f"[Gitea] 组织不存在，正在创建: {org_name}")
        try:
            create_url = self._get_api_url("/orgs")
            org_data = {"username": org_name, "visibility": "public"}

            if self.token:
                response = self.session.post(
                    create_url, json=org_data, headers=self._get_headers(), timeout=30
                )
            else:
                response = self.session.post(
                    create_url, json=org_data, auth=self._get_auth(), timeout=30
                )

            if response.status_code in [201, 200]:
                logger.info(f"[Gitea] 组织创建成功: {org_name}")
                return True
            else:
                error_msg = response.text
                if response.status_code == 422:
                    # 可能是组织已存在
                    logger.warning(
                        f"[Gitea] 创建组织失败，可能已存在: HTTP {response.status_code}"
                    )
                    return self.get_org(org_name) is not None
                else:
                    logger.error(
                        f"[Gitea] 创建组织失败: HTTP {response.status_code} - {error_msg}"
                    )
                    return False

        except Exception as exc:
            logger.error(f"[Gitea] 创建组织异常: {exc}")
            return False

    def create_repo(
        self,
        repo_name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
        org_name: Optional[str] = None,
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
                "auto_init": auto_init,
            }

            if self.token:
                response = self.session.post(
                    create_url, json=repo_data, headers=self._get_headers(), timeout=30
                )
            else:
                response = self.session.post(
                    create_url, json=repo_data, auth=self._get_auth(), timeout=30
                )

            if response.status_code in [201, 200]:
                repo_info = response.json()
                logger.info(f"[Gitea] 仓库创建成功: {repo_name}")
                return repo_info
            elif response.status_code == 409:
                logger.warning(f"[Gitea] 仓库已存在: {repo_name}")
                # 获取现有仓库信息
                if org_name:
                    repo_path = f"{org_name}/{repo_name}"
                else:
                    repo_path = f"{self.username}/{repo_name}"
                get_url = self._get_api_url(f"/repos/{repo_path}")
                if self.token:
                    resp = self.session.get(
                        get_url, headers=self._get_headers(), timeout=10
                    )
                else:
                    resp = self.session.get(get_url, auth=self._get_auth(), timeout=10)
                if resp.status_code == 200:
                    return resp.json()
                return None
            else:
                logger.error(
                    f"[Gitea] 创建仓库失败: HTTP {response.status_code} - {response.text}"
                )
                return None

        except Exception as exc:
            logger.error(f"[Gitea] 创建仓库异常: {exc}")
            return None

    def get_repo_clone_url(self, repo_info: Dict[str, Any]) -> str:
        """获取仓库的克隆 URL（带认证信息，密码做 URL 编码）"""
        clone_url = repo_info.get("clone_url", "")
        if not clone_url:
            return ""

        # 将 http:// 替换为带认证信息的 URL
        # 格式: http://username:password@host/path
        # 注意：password 需要做 URL 编码，避免其中的 @、: 等特殊字符破坏 URL 结构
        encoded_password = quote(self.password, safe="")

        if clone_url.startswith("http://"):
            url_part = clone_url.replace("http://", "")
            return f"http://{self.username}:{encoded_password}@{url_part}"
        elif clone_url.startswith("https://"):
            url_part = clone_url.replace("https://", "")
            return f"https://{self.username}:{encoded_password}@{url_part}"
        return clone_url


# 初始化全局 Gitea 服务实例（类似 Neo4j driver 和 Milvus 连接的模式）
gitea_service = GiteaService(
    base_url=GITEA_URL, username=GITEA_ADMIN_USER, password=GITEA_ADMIN_PASSWORD
)

# 在模块加载时进行认证
try:
    if gitea_service.authenticate():
        logger.info(f"Gitea 服务初始化成功: {GITEA_URL}")
    else:
        logger.warning(f"Gitea 服务初始化失败，将使用 Basic Auth")
except Exception as e:
    logger.warning(f"Gitea 服务初始化异常: {e}，将使用 Basic Auth")


def upload_to_gitea(
    extract_dir: str, repo_name: str, description: str = ""
) -> Tuple[Optional[str], Optional[str]]:
    """
    将文件夹上传到 Gitea 并返回仓库的 web_url 和分支名称

    Args:
        extract_dir: 要上传的文件夹路径
        repo_name: 仓库名称
        description: 仓库描述

    Returns:
        成功返回仓库的 web_url 和分支名称，失败返回 None 和 None
    """
    try:
        extract_dir = os.path.abspath(extract_dir)
        if not os.path.exists(extract_dir):
            logger.error(f"[upload_to_gitea] 文件夹不存在: {extract_dir}")
            return None, None

        if not os.path.isdir(extract_dir):
            logger.error(f"[upload_to_gitea] 路径不是文件夹: {extract_dir}")
            return None, None

        # 使用全局 gitea_service 实例
        service = gitea_service

        # 确保组织存在
        if not service.ensure_org_exists(GITEA_ORG_NAME):
            logger.error(f"[upload_to_gitea] 无法确保组织存在: {GITEA_ORG_NAME}")
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
            logger.error("[upload_to_gitea] 无法创建或获取仓库")
            return None, None

        # 获取克隆 URL（带认证信息）
        clone_url = service.get_repo_clone_url(repo_info)
        if not clone_url:
            logger.error("[upload_to_gitea] 无法获取仓库克隆 URL")
            return None, None

        logger.info(f"[upload_to_gitea] 开始上传文件夹内容到仓库...")
        logger.info(f"[upload_to_gitea] 源文件夹: {extract_dir}")
        logger.info(f"[upload_to_gitea] 仓库: {GITEA_ORG_NAME}/{repo_name}")

        # 切换到文件夹目录
        original_cwd = os.getcwd()
        os.chdir(extract_dir)

        try:
            # 检查是否已经是 git 仓库
            if os.path.exists(".git"):
                logger.info("[upload_to_gitea] 检测到已有 .git 目录，将使用现有仓库")
            else:
                # 初始化 git 仓库
                logger.info("[upload_to_gitea] 初始化 Git 仓库...")
                subprocess.run(["git", "init"], check=True, capture_output=True)

            # 添加所有文件
            logger.info("[upload_to_gitea] 添加文件到 Git...")
            subprocess.run(["git", "add", "."], check=True, capture_output=True)

            # 检查是否有变更
            result = subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True
            )
            if not result.stdout.strip():
                logger.info("[upload_to_gitea] 没有文件变更，跳过提交")
            else:
                # 提交
                logger.info("[upload_to_gitea] 提交文件...")
                subprocess.run(
                    ["git", "commit", "-m", "Initial commit: upload from folder"],
                    check=True,
                    capture_output=True,
                )

            # 添加远程仓库（如果已存在则先删除）
            logger.info("[upload_to_gitea] 配置远程仓库...")
            subprocess.run(["git", "remote", "remove", "origin"], capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", clone_url], check=True)

            # 推送代码
            logger.info("[upload_to_gitea] 推送代码到 Gitea...")
            branch_name = "main"
            # 尝试推送到 main 分支，如果失败则尝试 master
            try:
                subprocess.run(
                    ["git", "push", "-u", "origin", "HEAD:main", "--force"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logger.info("[upload_to_gitea] 代码已推送到 main 分支")
            except subprocess.CalledProcessError:
                try:
                    subprocess.run(
                        ["git", "push", "-u", "origin", "HEAD:master", "--force"],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    logger.info("[upload_to_gitea] 代码已推送到 master 分支")
                    branch_name = "master"
                except subprocess.CalledProcessError as e:
                    logger.error(
                        f"[upload_to_gitea] 推送失败: {e.stderr if e.stderr else e}"
                    )
                    return None, None

            # 恢复原始工作目录
            os.chdir(original_cwd)

            web_url = repo_info.get("html_url", "")
            logger.info(f"[upload_to_gitea] 文件夹内容已成功上传到 Gitea 仓库")
            logger.info(f"[upload_to_gitea] 仓库 Web URL: {web_url}")
            return web_url, branch_name

        except subprocess.CalledProcessError as e:
            logger.error(
                f"[upload_to_gitea] Git 操作失败: {e.stderr.decode() if e.stderr else str(e)}"
            )
            try:
                os.chdir(original_cwd)
            except:
                pass
            return None, None
        except Exception as e:
            logger.error(f"[upload_to_gitea] 上传过程异常: {e}")
            try:
                os.chdir(original_cwd)
            except:
                pass
            return None, None

    except Exception as e:
        logger.error(f"[upload_to_gitea] 上传失败: {e}")
        return None, None


def upload_file_to_gitea(
    file_path: str, repo_name: str, description: str = ""
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
            logger.error(f"[upload_file_to_gitea] 文件不存在: {file_path}")
            return None, None

        if not os.path.isfile(file_path):
            logger.error(f"[upload_file_to_gitea] 路径不是文件: {file_path}")
            return None, None

        # 使用全局 gitea_service 实例
        service = gitea_service

        # 确保组织存在
        if not service.ensure_org_exists(GITEA_ORG_NAME):
            logger.error(f"[upload_file_to_gitea] 无法确保组织存在: {GITEA_ORG_NAME}")
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
            logger.error("[upload_file_to_gitea] 无法创建或获取仓库")
            return None, None

        # 获取克隆 URL（带认证信息）
        clone_url = service.get_repo_clone_url(repo_info)
        if not clone_url:
            logger.error("[upload_file_to_gitea] 无法获取仓库克隆 URL")
            return None, None

        logger.info(f"[upload_file_to_gitea] 开始上传文件到仓库...")
        logger.info(f"[upload_file_to_gitea] 源文件: {file_path}")
        logger.info(f"[upload_file_to_gitea] 仓库: {GITEA_ORG_NAME}/{repo_name}")

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
            logger.info(
                f"[upload_file_to_gitea] 文件已复制到临时目录: {dest_file_path}"
            )

            # 切换到临时目录
            os.chdir(tmp_root)

            # 初始化 git 仓库
            logger.info("[upload_file_to_gitea] 初始化 Git 仓库...")
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
            logger.info("[upload_file_to_gitea] 添加文件到 Git...")
            subprocess.run(["git", "add", file_name], check=True, capture_output=True)

            # 提交
            logger.info("[upload_file_to_gitea] 提交文件...")
            commit_message = f"Upload file: {file_name}"
            subprocess.run(
                ["git", "commit", "-m", commit_message], check=True, capture_output=True
            )

            # 添加远程仓库
            logger.info("[upload_file_to_gitea] 配置远程仓库...")
            subprocess.run(["git", "remote", "add", "origin", clone_url], check=True)
            branch_name = "main"
            
            # 推送代码
            logger.info("[upload_file_to_gitea] 推送代码到 Gitea...")
            # 尝试推送到 main 分支，如果失败则尝试 master
            try:
                subprocess.run(
                    ["git", "push", "-u", "origin", "HEAD:main", "--force"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logger.info("[upload_file_to_gitea] 代码已推送到 main 分支")
            except subprocess.CalledProcessError:
                try:
                    subprocess.run(
                        ["git", "push", "-u", "origin", "HEAD:master", "--force"],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    logger.info("[upload_file_to_gitea] 代码已推送到 master 分支")
                    branch_name = "master"
                except subprocess.CalledProcessError as e:
                    logger.error(
                        f"[upload_file_to_gitea] 推送失败: {e.stderr if e.stderr else e}"
                    )
                    return None, None
            web_url = repo_info.get("html_url", "")
            logger.info(f"[upload_file_to_gitea] 文件已成功上传到 Gitea 仓库")
            logger.info(f"[upload_file_to_gitea] 仓库 Web URL: {web_url}")
            return web_url, branch_name

        except subprocess.CalledProcessError as e:
            logger.error(
                f"[upload_file_to_gitea] Git 操作失败: {e.stderr.decode() if e.stderr else str(e)}"
            )
            try:
                os.chdir(original_cwd)
            except:
                pass
            return None, None
        except Exception as e:
            logger.error(f"[upload_file_to_gitea] 上传过程异常: {e}")
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
                    logger.info(f"[upload_file_to_gitea] 临时目录已清理: {tmp_root}")
                except Exception as e:
                    # Windows 删除失败很常见（文件被占用），记录警告但不影响主流程
                    logger.warning(
                        f"[upload_file_to_gitea] 临时目录删除失败（Windows 常见问题）: {tmp_root}, "
                        f"错误: {e}。目录将在后续手动清理或系统重启时自动清理。"
                    )

    except Exception as e:
        logger.error(f"[upload_file_to_gitea] 上传失败: {e}")
        return None, None
