# 红队知识库说明
## 已入库知识
/home/lyd/red-team-rag 下的neo4j_data 为neo4j数据
10.1.1.149:9200 为elasticsearch数据

## 上传新数据脚本
batch_import.py batch_import_code.py

在脚本代码的主函数中设置要上传的文件位置，以及批次号（用于区分是第几次上传的）和并发数
在settings.py中设置数据库连接信息，使用red-team-rag的conda 环境
> python batch_import.py

> python batch_import_code.py

## 验证数据
查看某个批次的文档数和软件数
> python verify_batch.py <批次数> 