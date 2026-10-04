# 本机模型比较复现说明

## 环境与固定权重

本轮在Apple arm64、24GiB内存的机器上，使用Python3.11.15的独立 `/private/tmp/plan-a-rag-model-venv`；项目原venv没有安装这些模型依赖。完整依赖版本见[requirements](2026-10-04-local-model-requirements.txt)，文件大小、SHA256、许可证和本机路径见[下载清单](2026-10-04-local-model-download-manifest.json)。模型文件没有提交到Git。

| 模型 | 固定revision | 用途 |
| --- | --- | --- |
| [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | 小型多语双塔召回，query/passage前缀分开 |
| [bge-m3](https://huggingface.co/BAAI/bge-m3) | `5617a9f61b028005a4858fdac845db406aefb181` | 多语dense召回；本轮没有启用模型自身的sparse或multi-vector功能 |
| [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | query/passage交叉编码精排 |

推理固定CPU、float32、4线程、batch4、截断512 tokens。每次比较同时驻留一个embedding和一个reranker，模型选择按独立进程串行运行。进程峰值内存不是单次查询、单模型或单个arm的峰值。

## 在另一台机器准备文件

先建立独立venv，并安装锁定依赖；安装与权重下载需要联网，检索评测本身离线。以下示例从仓库根目录执行，使用已核验清单的固定revision与文件名，不读取本地 `.env` 或发送研究资料。

```sh
python3 -m venv /private/tmp/plan-a-rag-model-venv
/private/tmp/plan-a-rag-model-venv/bin/python -m pip install -r docs/optimization/2026-10-04-local-model-requirements.txt
```

用同一venv执行下面的Python代码，将 `target` 改为自己的权重目录。它会生成独立复现清单，保留原验收清单。

```python
import hashlib, json
from pathlib import Path
from huggingface_hub import snapshot_download

original = Path('docs/optimization/2026-10-04-local-model-download-manifest.json')
manifest = json.loads(original.read_text())
target = Path('/private/tmp/plan-a-rag-models')
for model in manifest['models']:
    folder = target / model['model_id'].replace('/', '--') / model['revision']
    snapshot_download(model['model_id'], revision=model['revision'], token=False,
                      allow_patterns=[f['file'] for f in model['files'] if not f.get('derived')],
                      local_dir=folder, max_workers=2)
    if model.get('conversion'):
        import torch
        from safetensors.torch import save_file
        state = torch.load(folder / 'pytorch_model.bin', map_location='cpu',
                           weights_only=True, mmap=True)
        assert isinstance(state, dict)
        assert all(isinstance(k, str) and isinstance(v, torch.Tensor) for k, v in state.items())
        save_file({k: v.contiguous() for k, v in state.items()},
                  folder / 'model.safetensors', metadata={'format': 'pt'})
        del state
    for entry in model['files']:
        file = folder / entry['file']
        sha = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(block)
        assert file.stat().st_size == entry['bytes'], file
        assert sha.hexdigest() == entry['sha256'], file
    model['local_path'] = str(folder.resolve())
Path('/private/tmp/plan-a-reproduction-manifest.json').write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
```

BGE-M3此revision只有原始 `pytorch_model.bin`，因此本机以 `weights_only=True` 受限读取tensor字典，再转为safetensors。原始与转换文件均核验SHA256。加载不启用远程代码；转换失败或哈希不同应停止，不改清单消除错误。

## 离线比较

以下命令运行审核资料的8组比较：原问题/自动结构化查询，各自比较sparse、dense、hybrid RRF、hybrid加精排。换成另一个embedding时使用新的Python进程。CLI会校验模型文件、冻结资料与核心代码指纹，并将初始化调用与评测调用分开记录。

```sh
COMPETISCOPE_LOAD_ENV_FILES=0 /private/tmp/plan-a-rag-model-venv/bin/python backend/scripts/compare_local_retrieval_models.py \
  --manifest /private/tmp/plan-a-reproduction-manifest.json \
  --embedding-model intfloat/multilingual-e5-small \
  --corpus eval/product-research-reviewed-v2-corpus.jsonl \
  --queries eval/product-research-reviewed-v2-queries.jsonl \
  --labels eval/product-research-reviewed-v2-labels.jsonl \
  --mode formal --threads 4 --output /private/tmp/e5-reviewed-comparison.json
```

评测不依赖DeepSeek、Perplexity、Docker或Qdrant HTTP服务；使用临时SQLite和Qdrant本地目录，运行结束关闭并清理。权重可从本机目录离线读取；外部推理调用应为0。结果只评估固定资料检索，不生成答案，不执行Ragas，也不证明完整RAG已经合格。
