# EngPaperTeacher

把英文论文（PDF）变成可交互的精读材料：点词翻译、句子翻译、语块划分、课程化学案、朗读。

## 功能

- **阅读 + 点词翻译**：离线 ECDICT（340 万词条）+ Google / MyMemory 在线兜底
- **句子翻译**：免费在线翻译；失败时可用已配置的 LLM 兜底
- **语块划分**：本地 spaCy 依存句法 + LLM 精修
- **课程模式**：单元划分、七板块学案、练习判分、批量生成、词库管理 + TSV 导出
- **朗读**：单词 / 单句 / 段落 / 全篇；edge-tts 神经语音 → Google TTS → 浏览器语音三级兜底，磁盘缓存
- **文档管理**：上传、切换、重命名、重新解析、删除；同名不同内容自动生成新版本，避免脏数据

## 安装

需要 Python 3.10+（当前开发环境为 3.13）。

**一键安装**：把 `ecdict-sqlite-28.zip` 放到 `data/` 后双击 `setup_engpaper.bat`。

手动安装：

```powershell
# 1) 创建虚拟环境
uv venv .venv
# 或者：python -m venv .venv

# 2) 安装依赖（含 en_core_web_sm 模型）
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
# 或者：.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3) 安装离线词典：把 ecdict-sqlite-28.zip 放到 data/ 后执行
.venv\Scripts\python.exe tools\install_dict.py

# 4) 生成本地配置
copy config.example.json config.json
```

依赖说明：

- `en_core_web_sm` 已通过 `requirements.txt` 中的 wheel URL 安装。
- 离线词典较大（`data/stardict.db` 约 850MB），`data/` 不入库，需要单独安装。
- `edge-tts` 必须为 `7.3.1` 或更新版本，旧版本会因微软端点变更返回 403。

## 运行

- 双击 `start_engpaper.bat` → 自动打开 http://127.0.0.1:8765（已有实例则直接打开浏览器）。
- 或手动：`.venv\Scripts\python.exe serve.py`
- 关闭自动开浏览器：设置环境变量 `EPT_NO_BROWSER=1`。
- 仅启动开发服务：`.venv\Scripts\python.exe tools\dev_server.py 8765`

LLM 配置在前端右上角「设置」中填写，仅保存在本机浏览器 `localStorage`；API Key 不会写入服务端。课程学案与语块精修需要 LLM。

## 测试

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

手工检查：

- `.venv\Scripts\python.exe tools\check_dict.py`
- `.venv\Scripts\python.exe tools\check_chunk.py`
- `.venv\Scripts\python.exe tools\check_parse.py data/docs/main/source.pdf`
- 模拟 LLM（无需 key）：`.venv\Scripts\python.exe tools\mock_llm.py 8899`，Base URL 填 `http://127.0.0.1:8899/v1`

## 配置

`config.json`：

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "proxy": "",
  "translate_contact": "",
  "max_upload_mb": 80,
  "tts_cache_max_files": 2000
}
```

- 仓库只提供 `config.example.json`；请复制为 `config.json` 后按需修改，`config.json` 已被忽略，不会提交。
- `proxy` 同时用于在线翻译、LLM 和 edge-tts；不可用时自动直连。
- `translate_contact` 可填邮箱，用于提升 MyMemory 翻译配额（可留空）。
- `max_upload_mb` 限制单个 PDF 大小，默认 80MB。
- `tts_cache_max_files` 控制 TTS 磁盘缓存上限，超出后清理最旧文件。

## 结构

```
app/        FastAPI 后端（pdf_parse / dict_lookup / translate / chunking / llm / course / tts）
static/     前端（单页）
data/       词典、上传论文、词库、TTS 缓存（本地，不入库）
tools/      安装/检查/mock 脚本
tests/      pytest 测试
setup_engpaper.bat  一键安装
start_engpaper.bat  启动
config.json host/port/proxy 等配置
```

## 隐私与安全

- 应用默认只监听 `127.0.0.1`，上传的 PDF、词库、词典和 TTS 缓存都只保存在本机 `data/`。
- LLM API Key 仅保存在浏览器 `localStorage`，通过请求体发送给本地服务，不写入服务端文件或日志。
- `data/`、`config.json`、虚拟环境、缓存和日志均已加入 `.gitignore`，不会进入开源仓库。
- 请勿把包含个人论文、笔记或密钥的本地数据提交到公开仓库。

## 已知限制

- 免费在线翻译与 TTS 使用非官方端点，可能受网络、地区或频率限制；应用已做重试、代理/直连切换和本地/浏览器兜底。
- PDF 解析针对单栏/双栏学术论文做了启发式处理；扫描版 PDF 需先 OCR，复杂图表/公式会被丢弃。
- 学案与语块精修质量取决于所配置的 LLM。

## License

MIT，详见 [LICENSE](LICENSE)。
