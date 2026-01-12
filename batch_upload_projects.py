import os
import re
import sys
import subprocess
import requests
from typing import Optional, Dict, Any, List
from urllib.parse import quote
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


def upload_folder_to_gitea(
    folder_path: str,
    repo_name: Optional[str] = None,
    org_name: Optional[str] = None,
    description: str = "",
    service: Optional[GiteaService] = None
) -> Optional[str]:
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
        if not repo_info.get("html_url"):
            return False
        return repo_info.get("html_url")

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

def update_repo_url(repo_url: str, software_name: str) -> List[str]:
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
                session.run(
                    "MATCH (n:MitreAttackCodeSoftwareFile) WHERE elementId(n) = $element_id AND n.repo_url IS NULL SET n.repo_url = $repo_url",
                    element_id=file_node.element_id, repo_url=repo_url
                )
                print(f"[INFO] 更新 File 节点 repo_url: {file_node.element_id}")

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
                    element_id=code_node.element_id, repo_url=repo_url
                )
                print(f"[INFO] 更新 CodeChunk 节点 repo_url: {code_node.element_id}")

            print(f"[OK] 成功更新 {len(unique_file_nodes)} 个 File 节点和 {len(unique_code_nodes)} 个 CodeChunk 节点的 repo_url")
            return code_chunk_element_ids

    except Exception as e:
        print(f"[FAIL] 更新仓库 URL 失败: {e}")
        return []

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
        repo_url = upload_folder_to_gitea(
            folder_path=folder_path,
            repo_name=folder_name,
            org_name=org_name,
            description=description,
            service=service
        )
        if not repo_url:
            print(f"[FAIL] 上传失败: {folder_name}")
            continue
        code_chunk_element_ids = update_repo_url(repo_url, folder_name)
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