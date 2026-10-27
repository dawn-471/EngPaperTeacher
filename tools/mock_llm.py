"""Mock OpenAI-compatible LLM server for testing EPT without a real API key.

Usage: .venv/Scripts/python.exe tools/mock_llm.py [port]   (default 8899)

- GET  /v1/models            -> a model list
- POST /v1/chat/completions  -> canned responses:
    * prompts containing "sense groups"  -> chunk-refine JSON
    * everything else                    -> a sample lesson JSON
"""
import json
import sys

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI(title="EPT Mock LLM")


def _canned_lesson(first_line: str):
    return {
        "overview": {"questions": [
            "这段主要讲了什么？（一段话概括）",
            "作者用这个实验想验证什么？",
        ]},
        "sentences": [
            {"text": first_line,
             "structure": "主语 + 谓语 + 宾语；mock 数据（真实生成时这里会是长难句拆解）",
             "translation": "（mock）这句的参考译文。"},
        ],
        "vocab": [
            {"word": "compost", "pos": "n./v.", "meaning_cn": "堆肥；制作堆肥",
             "collocations": "kitchen compost", "word_family": "composting",
             "example": "We add kitchen scraps to the compost."},
            {"word": "harvest", "pos": "n./v.", "meaning_cn": "收获；收割",
             "collocations": "summer harvest", "word_family": "harvests / harvested",
             "example": "The summer harvest was plentiful."},
            {"word": "rotate", "pos": "v.", "meaning_cn": "轮换；轮作",
             "collocations": "rotate crops", "word_family": "rotation / rotated",
             "example": "Farmers rotate crops to protect the soil."},
        ],
        "grammar": [
            {"point": "定语从句", "explain": "that 引导限制性定语从句，修饰先行词。",
             "example": "plots that residents can rent"},
        ],
        "paraphrase": [
            {"original": "improve the soil", "alternative": "enrich / build up the soil", "note": "写作常用同义替换"},
        ],
        "exercises": [
            {"type": "tfng", "question": "The garden only grows flowers.",
             "answer": "F", "explain": "原文提到蔬菜和香草。"},
            {"type": "cloze", "question": "We add kitchen scraps to the ____.", "answer": "compost", "explain": "固定搭配"},
            {"type": "translate", "question": "Translate: 'The garden supplies fresh vegetables.'",
             "answer": "菜园供应新鲜蔬菜。", "explain": "supply sth. to sb."},
        ],
        "output": [{"task": "用自己的话复述这一段（3-4 句英文）。"}],
    }


@app.get("/v1/models")
def models():
    return {"data": [{"id": "mock-model"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    content = ""
    try:
        content = body["messages"][-1]["content"]
    except Exception:
        pass

    if "Reply with exactly: OK" in content:
        reply = "OK"
    elif "Translate the following English passage" in content:
        reply = "（mock 译文）菜园供应新鲜蔬菜。"
    elif "sense groups" in content:
        reply = json.dumps(
            {"chunks": [{"text": "Mock group", "label": "主语", "note": "mock"}],
             "summary": "mock refine summary"},
            ensure_ascii=False)
    else:
        parts = content.split("---")
        seg_text = parts[1] if len(parts) > 2 else content
        lines = [ln.strip() for ln in seg_text.splitlines() if ln.strip()]
        first_line = lines[0][:140] if lines else "Mock segment."
        reply = json.dumps(_canned_lesson(first_line), ensure_ascii=False)

    return {"choices": [{"message": {"role": "assistant", "content": reply}}]}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
