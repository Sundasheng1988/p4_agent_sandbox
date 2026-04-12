# query_rewriter.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.llm_client import generate_with_ollama


@dataclass
class RewriteResult:
    original_query: str
    rewritten_query: str
    rewrite_mode: str
    applied: bool
    reason: str = ""
    meta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_query": self.original_query,
            "rewritten_query": self.rewritten_query,
            "rewrite_mode": self.rewrite_mode,
            "applied": self.applied,
            "reason": self.reason,
            "meta": self.meta or {},
        }


class BaseQueryRewriter:
    def rewrite(self, query: str) -> RewriteResult:
        raise NotImplementedError


class RuleBasedQueryRewriter(BaseQueryRewriter):
    """
    第一版规则重写器：
    - 轻量中英术语归一
    - 保留原词，补充中文同义词
    - 尽量不改坏原始 query
    """

    TERM_MAP = {
        # autonomous driving
        "planning": "规划",
        "perception": "感知",
        "localization": "定位",
        "prediction": "预测",
        "trajectory": "轨迹",
        "map": "地图",
        "lane": "车道",
        "ego": "自车",
        "adas": "辅助驾驶",
        "autonomous driving": "自动驾驶",
        "self-driving": "自动驾驶",
        "selfdriving": "自动驾驶",

        # robotics
        "grasp": "抓取",
        "robot arm": "机械臂",
        "robotics": "机器人",
        "servo": "舵机",
        "inverse kinematics": "逆运动学",
        "ik": "逆运动学",
        "vision": "视觉",
        "camera": "相机",
        "manipulation": "操作",
        "motion planning": "运动规划",

        # agent / rag
        "retrieval": "检索",
        "rerank": "重排",
        "router": "路由",
        "routing": "路由",
        "embedding": "向量",
        "vector": "向量",
        "knowledge base": "知识库",
        "rag": "检索增强生成",
        "planner": "规划器",
        "orchestrator": "编排器",
        "runtime": "运行时",
        "tool": "工具",
        "tools": "工具",
        "semantic search": "语义搜索",
    }

    def _normalize_spaces(self, text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _contains_ci(self, text: str, needle: str) -> bool:
        return needle.lower() in text.lower()

    def rewrite(self, query: str) -> RewriteResult:
        original = self._normalize_spaces(query)
        if not original:
            return RewriteResult(
                original_query=query,
                rewritten_query=query,
                rewrite_mode="rule",
                applied=False,
                reason="empty_query",
                meta={},
            )

        rewritten = original
        applied_rules = []

        # 先处理长词，避免被短词打断
        for src, dst in sorted(self.TERM_MAP.items(), key=lambda x: len(x[0]), reverse=True):
            if self._contains_ci(rewritten, src):
                # 如果中文目标词已经存在，则不重复补
                if dst not in rewritten:
                    rewritten = f"{rewritten} {dst}"
                    applied_rules.append(f"{src}->{dst}")

        rewritten = self._normalize_spaces(rewritten)

        applied = rewritten != original
        reason = "rule_expand_terms" if applied else "no_rule_applied"

        return RewriteResult(
            original_query=original,
            rewritten_query=rewritten,
            rewrite_mode="rule",
            applied=applied,
            reason=reason,
            meta={
                "applied_rules": applied_rules,
            },
        )


class LLMQueryRewriter(BaseQueryRewriter):
    """
    第二版 LLM 重写器：
    - 受控输出 JSON
    - 保留核心实体
    - 只做检索友好的归一化/扩展
    """

    SYSTEM_PROMPT = """你是一个知识库检索 Query Rewriter。

你的任务：
把用户查询改写成更适合知识库检索的短查询。

严格要求：
1. 保留原始意图，不要改变问题方向
2. 保留核心实体、关键词、专有名词
3. 如有必要，可补充中英文同义表达
4. 不要引入原问题中不存在的新事实
5. 输出必须是 JSON 对象，不要输出 markdown

输出格式：
{
  "rewritten_query": "...",
  "reason": "..."
}
"""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct", timeout: int = 30):
        self.model_name = model_name
        self.timeout = timeout

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()

        # 去掉 markdown code fence
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise ValueError("no JSON object found in rewrite output")

        obj = json.loads(m.group(0))
        if not isinstance(obj, dict):
            raise ValueError("rewrite output is not an object")
        return obj

    def rewrite(self, query: str) -> RewriteResult:
        original = (query or "").strip()
        if not original:
            return RewriteResult(
                original_query=query,
                rewritten_query=query,
                rewrite_mode="llm",
                applied=False,
                reason="empty_query",
                meta={},
            )

        prompt = f"""{self.SYSTEM_PROMPT}

用户原始查询：
{original}

请直接输出 JSON：
"""

        llm_out = generate_with_ollama(
            prompt=prompt,
            model_name=self.model_name,
            timeout=self.timeout,
        )

        raw_text = (llm_out.get("response") or "").strip()
        obj = self._extract_json(raw_text)

        rewritten = str(obj.get("rewritten_query", "")).strip()
        reason = str(obj.get("reason", "")).strip()

        if not rewritten:
            rewritten = original

        return RewriteResult(
            original_query=original,
            rewritten_query=rewritten,
            rewrite_mode="llm",
            applied=(rewritten != original),
            reason=reason or "llm_rewrite",
            meta={
                "model_name": llm_out.get("model", self.model_name),
                "raw_text": raw_text,
            },
        )


def rewrite_query(
    query: str,
    mode: str = "rule",
    *,
    model_name: str = "qwen2.5:7b-instruct",
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    统一入口：
    - mode="rule"
    - mode="llm"

    返回 dict，便于直接写 audit / debug 输出
    """
    mode = (mode or "rule").strip().lower()

    if mode == "llm":
        rewriter = LLMQueryRewriter(model_name=model_name, timeout=timeout)
    else:
        rewriter = RuleBasedQueryRewriter()

    result = rewriter.rewrite(query)
    return result.to_dict()