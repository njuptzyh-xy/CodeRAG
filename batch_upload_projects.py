import os
import sys
import subprocess
import requests
from typing import Optional, Dict, Any, List
from urllib.parse import quote


# Gitea 配置
GITEA_URL = os.getenv('GITEA_URL', 'http://10.1.1.155:3000')
GITEA_ADMIN_USER = os.getenv('GITEA_ADMIN_USER', 'root')
GITEA_ADMIN_PASSWORD = os.getenv('GITEA_ADMIN_PASSWORD', 'Admin@1234')
GITEA_ORG_NAME = os.getenv('GITEA_ORG_NAME', 'red_team_rag')


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


def upload_folder_to_gitea(
    folder_path: str,
    repo_name: Optional[str] = None,
    org_name: Optional[str] = None,
    description: str = "",
    service: Optional[GiteaService] = None
) -> bool:
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
        return False

    if not os.path.isdir(folder_path):
        print(f"[FAIL] 路径不是文件夹: {folder_path}")
        return False

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
            return False

    # 确定组织名称
    target_org_name = org_name or GITEA_ORG_NAME

    # 确保组织存在
    if target_org_name:
        if not service.ensure_org_exists(target_org_name):
            print(f"[FAIL] 无法确保组织存在: {target_org_name}")
            return False

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
        return False

    # 获取克隆 URL（带认证信息）
    clone_url = service.get_repo_clone_url(repo_info)
    if not clone_url:
        print("[FAIL] 无法获取仓库克隆 URL")
        return False

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
            except subprocess.CalledProcessError as e:
                print(f"[FAIL] 推送失败: {e.stderr if e.stderr else e}")
                return False

        # 恢复原始工作目录
        os.chdir(original_cwd)

        print(f"[OK] 文件夹内容已成功上传到 Gitea 仓库")
        return True

    except subprocess.CalledProcessError as e:
        print(f"[FAIL] Git 操作失败: {e.stderr.decode() if e.stderr else str(e)}")
        try:
            os.chdir(original_cwd)
        except:
            pass
        return False
    except Exception as e:
        print(f"[FAIL] 上传过程异常: {e}")
        try:
            os.chdir(original_cwd)
        except:
            pass
        return False


def batch_upload_folders(
    base_path: str,
    org_name: Optional[str] = None,
    description_template: str = "项目批量上传"
) -> Dict[str, bool]:
    """
    批量上传文件夹到 Gitea

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

    for i, folder_path in enumerate(subfolders, 1):
        folder_name = os.path.basename(folder_path)
        print(f"\n[{i}/{len(subfolders)}] 正在处理: {folder_name}")
        print("-" * 80)

        description = f"{description_template} - {folder_name}"
        success = upload_folder_to_gitea(
            folder_path=folder_path,
            repo_name=folder_name,
            org_name=org_name,
            description=description,
            service=service
        )

        results[folder_path] = success
        if success:
            success_count += 1
        else:
            fail_count += 1

        print(f"[{'OK' if success else 'FAIL'}] {folder_name}: {'成功' if success else '失败'}")

    # 打印总结
    print("\n" + "=" * 80)
    print("批量上传完成！")
    print(f"总计: {len(subfolders)} 个文件夹")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")

    if fail_count > 0:
        print("\n失败的文件夹:")
        for folder_path, success in results.items():
            if not success:
                print(f"  - {folder_path}")

    return results


def main():
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

    results = batch_upload_folders(
        base_path=base_path,
        org_name=org_name,
        description_template=description_template
    )

    # 判断是否全部成功
    if results and all(results.values()):
        print("\n所有文件夹上传成功！")
        sys.exit(0)
    elif results:
        print(f"\n部分文件夹上传失败！")
        sys.exit(1)
    else:
        print("\n没有文件夹被上传！")
        sys.exit(1)


if __name__ == "__main__":
    main()