# 本机真实多语检索比较设计

基线：06d785a。用户已允许下载开源 embedding 和精排权重、仅本机运行测试，并逐项提供 008/023/026/028/030 的人审意见；执行该已确认方向，不重复请求许可。

## 范围与选择

比较 intfloat/multilingual-e5-small、BAAI/bge-m3 的 dense，与现有 SQLite FTS 的 RRF 融合，再用 BAAI/bge-reranker-v2-m3 精排。相比仅运行一个模型，可观察轻量模型与既有 BGE 配置的差异；不在本轮加入微调或更多模型。

推理使用独立本机 Python 环境、CPU float32、小批次及固定 512-token 上限，模型串行运行；确认可用后也不自动切换设备。下载选官方公开仓库的固定 revision，不运行远端代码。E5和精排使用官方 safetensors；BGE-M3 该版本仅有 pytorch_model.bin，使用 torch.load(weights_only=True) 受限读取并本机转换为 safetensors，记录原文件与转换文件hash。权重、依赖缓存和临时向量库放在 /private/tmp，结果和复现代码入库，不把权重提交 Git。

## 模型合同

新适配器只接受现存本地目录与显式 model_id/revision，模型加载 local_files_only=True、trust_remote_code=False。缺依赖、加载失败、输出维数错误、NaN/Inf、分数数目不符必须失败，无 hash fallback。E5 文档加 passage:、查询加 query:；BGE-M3 不加前缀。输出规范化向量；精排使用 CrossEncoder 的 sigmoid 分数。

状态记录真实 model_id、revision、设备、维度、截断上限、加载耗时和本机推理调用数。评测外部模型调用为0不等于本机模型调用为0；两者分开报告。

## 评测路径

扩展既有 product_benchmark，默认 sparse 路径不变。显式 dense/hybrid 使用注入的真实适配器、临时 Qdrant 本地持久化和现有 IngestionPipeline/VectorStore/RetrievalService，不另写理想化打分模拟。SQL scope、产品、市场、role、as_of 和 canonical 回查沿用旧路径；每题冷响应缓存。模型状态在实际运行后重新读取，禁止未初始化/降级模型冒充真实成绩。

最终top_k=5，召回池20，RRF保持既有参数，MMR关闭，精排池20。不按评价集调阈值、关键词或意图；真实原题分别比较raw/structured，后者仅已有安全格式分离，无人为量身计划。记录文档召回、Top-1/MRR/NDCG、支持节选覆盖、非gold来源、分组、索引/检索时间和进程峰值内存，并明确每题授权过滤后的候选来源数量，避免Top-5覆盖全部小候选池被解释为语义正确。没有答案生成或Ragas，不能宣称全RAG质量通过。

## 新审核数据版本

旧三文件及词法词典保持冻结。新版本保留9条不同页面的旧来源作为干扰集，以7条补证资料替代5条同一官方页面的旧节选，共16条；原14条旧来源在旧corpus完整保留。替换关系记录于manifest，避免生产canonical规则将同一页面的两个版本同时视为active文档。5标签登记 project_user 的本轮明确审核及限制，不扩大到其他未审核题。问题文本保持，证据补充明确 provenance 与hash，不将事实查询从答案自动生成。

008期限月份保留推算与has_exact_day=false；023限定计费机制、缺具体金额时missing_entity_price；026录入官方开关实际核验的六个USD/每席位/月显示价格，annual指年付折合而非全年总价，tax_scope未知；028记录付费计划AND Full/Dev，基本检查仍可能对免费查看者开放；030分开90天可见与可选保存/删除策略，付费无限历史需受自定义删除设置限制。

新补证材料中的原文短引用每个网页不超过25词；摘要明确标识，不冒充连续原文。核查时间不代替发布/更新时间。资料进入隔离评测索引，不写入现有线上知识库或真实工作区。

## 验证与交付

适配器和评测入口分别TDD、fresh SPEC后QUALITY。先独立虚构数据验证限制、异常和真实Qdrant路径，冻结后回放旧候选与新审核版本。校验输入/代码/模型revision及文件hash，正式指标只针对人审范围且说明仅5题、存在曝光不能证明泛化。完整隔离后端、增量Ruff、最终审查和密钥扫描后按既有授权推送当前分支。

模型说明来源：[E5](https://huggingface.co/intfloat/multilingual-e5-small)、[BGE-M3](https://huggingface.co/BAAI/bge-m3)、[BGE reranker](https://huggingface.co/BAAI/bge-reranker-v2-m3)。
