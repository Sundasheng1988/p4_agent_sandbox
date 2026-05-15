# app/skills/financial/reasoner.py

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.core.hybrid_retrieval import hybrid_retrieve


def _clean_reason_text(text: str, max_len: int = 260) -> str:
    text = str(text or "").strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", "", text)

    if len(text) > max_len:
        text = text[:max_len].rstrip() + "……"

    return text


def _split_sentences(text: str) -> List[str]:
    text = str(text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n+", "", text)

    parts = re.split(r"[。；;]", text)
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def _is_valid_reason_sentence(sentence: str) -> bool:
    if not sentence:
        return False

    bad_words = [
        "目录",
        "重要提示",
        "董事会",
        "投资者",
        "不构成",
        "风险提示",
        "利润分配预案",
        "现金红利",
        "不送红股",
        "公积金转增股本",
        "适用",
        "不适用",
    ]

    if any(w in sentence for w in bad_words):
        return False

    reason_words = [
        "主要是",
        "主要系",
        "由于",
        "得益于",
        "受益于",
        "所致",
        "导致",
        "带动",
        "影响",
        "增加",
        "减少",
        "增长",
        "下降",
    ]

    return any(w in sentence for w in reason_words)


def _pick_reason_from_hits(
    hits: List[Dict[str, Any]],
    *,
    must_keywords: List[str],
    prefer_keywords: List[str],
) -> Dict[str, Any]:
    candidates = []

    for hit in hits:
        text = hit.get("full_text") or hit.get("snippet") or ""
        if not text:
            continue

        sentences = _split_sentences(text)

        for sentence in sentences:
            if not _is_valid_reason_sentence(sentence):
                continue

            score = 0

            if any(k in sentence for k in must_keywords):
                score += 30

            if any(k in sentence for k in prefer_keywords):
                score += 15

            if "主要是" in sentence or "主要系" in sentence:
                score += 30

            if "所致" in sentence or "导致" in sentence:
                score += 20

            if score <= 0:
                continue

            candidates.append(
                {
                    "score": score,
                    "reason": _clean_reason_text(sentence),
                    "evidence": _clean_reason_text(text, max_len=500),
                    "source": hit.get("filename", "知识库"),
                    "chunk_id": hit.get("chunk_id"),
                    "retrieval_score": hit.get("score"),
                    "rrf_score": hit.get("rrf_score"),
                }
            )

    if not candidates:
        return {
            "reason": "材料中未体现。",
            "evidence": "",
            "source": "知识库",
        }

    candidates.sort(
        key=lambda x: (
            x.get("score", 0),
            float(x.get("rrf_score") or 0),
            float(x.get("retrieval_score") or 0),
        ),
        reverse=True,
    )

    return candidates[0]

def _resolve_reason_filename(state: Dict[str, Any]) -> str | None:
    """
    原因抽取时要检索进入知识库的 markdown 文件，
    不是原始 PDF 文件。
    """

    registered = state.get("register_financial_markdown", {})
    if isinstance(registered, dict):
        md_filename = registered.get("markdown_filename")
        if md_filename:
            return md_filename

    inputs = state.get("collect_financial_inputs", {})
    filename = str(inputs.get("filename") or "").strip()

    if filename.lower().endswith(".pdf"):
        return filename.rsplit(".", 1)[0] + "_parsed.md"

    return filename or None


def _reason_specs() -> Dict[str, Dict[str, Any]]:
    return {
        "营业收入（元）": {
            "queries": [
                "营业收入 增长 原因 主要是 国内 海外 订单",
                "营业总收入 同比增长 主要是 销售区域 海外市场",
            ],
            "must": ["营业收入", "营业总收入", "收入"],
            "prefer": ["订单", "国内", "海外", "销售区域", "市场", "增长"],
        },
        "归属于上市公司股东的净利润（元）": {
            "queries": [
                "净利润 增长 原因 主要是 营业收入 订单 市场",
                "归属于母公司股东的净利润 同比增长 原因",
            ],
            "must": ["净利润", "利润"],
            "prefer": ["营业收入", "订单", "市场", "增长", "费用"],
        },
        "归属于上市公司股东的扣除非经常性损益的净利润（元）": {
            "queries": [
                "扣非净利润 增长 原因 主营 盈利质量",
                "扣除非经常性损益 净利润 同比增长 原因",
            ],
            "must": ["扣非", "扣除非经常性损益", "净利润"],
            "prefer": ["主营", "营业收入", "增长", "盈利"],
        },
        "经营活动产生的现金流量净额（元）": {
            "queries": [
                "经营活动产生的现金流量净额 下降 主要是 销售商品 购买商品 职工 税费",
                "经营活动现金净流量 与净利润 差异 原因 存货 经营性应收应付",
            ],
            "must": ["经营活动", "现金流"],
            "prefer": ["销售商品", "购买商品", "职工", "税费", "存货", "经营性应收应付"],
        },
        "毛利率": {
            "queries": [
                "毛利率 下降 原因 营业成本 原材料 产品结构",
                "产品整体毛利率 较上年同期下降 原因",
            ],
            "must": ["毛利率"],
            "prefer": ["营业成本", "原材料", "产品", "下降"],
        },
        "货币资金": {
            "queries": [
                "货币资金 重大变动说明 主要是 经营活动 投资支出 分配股利",
                "货币资金 期末 主要是 报告期经营活动产生的现金流量净额",
            ],
            "must": ["货币资金"],
            "prefer": ["经营活动", "投资支出", "分配股利", "主要是"],
        },
        "应收账款": {
            "queries": [
                "应收账款 重大变动说明 主要是 收入增加",
                "应收账款 增加 原因 销售业务量 收入增加",
            ],
            "must": ["应收账款"],
            "prefer": ["收入增加", "销售业务量", "主要是"],
        },
        "应付账款": {
            "queries": [
                "应付账款 重大变动说明 主要是 业务量增加",
                "应付账款 增加 原因 采购业务量",
            ],
            "must": ["应付账款"],
            "prefer": ["业务量增加", "采购业务量", "主要是"],
        },
        "存货": {
            "queries": [
                "存货 重大变动说明 主要是 业务量增加",
                "存货 增加 原因 业务量增加 存货跌价准备",
            ],
            "must": ["存货"],
            "prefer": ["业务量增加", "库存", "跌价准备", "主要是"],
        },
        "合同负债": {
            "queries": [
                "合同负债 重大变动说明 主要是 合同预付款增加",
                "合同负债 增加 原因 客户 合同预付款",
            ],
            "must": ["合同负债"],
            "prefer": ["合同预付款", "客户", "主要是"],
        },
        "销售费用": {
            "queries": [
                "销售费用 增长 重大变动说明 主要是 市场和销售投入",
                "销售费用 同比增长 主要是 报告期内加大市场和销售投入",
            ],
            "must": ["销售费用"],
            "prefer": ["市场和销售投入", "主要是"],
        },
        "管理费用": {
            "queries": [
                "管理费用 增长 重大变动说明 主要是 新业务培育 折旧费用",
                "管理费用 同比增长 主要是 新业务培育的投入以及折旧费用增加",
            ],
            "must": ["管理费用"],
            "prefer": ["新业务培育", "折旧费用", "主要是"],
        },
        "研发费用": {
            "queries": [
                "研发费用 增长 重大变动说明 主要是 研发投入 新产品开发",
                "研发费用 同比增长 报告期持续加强研发投入及新产品开发力度",
            ],
            "must": ["研发费用", "研发投入"],
            "prefer": ["研发投入", "新产品开发", "主要是"],
        },
    }


async def _retrieve_reason_for_metric(
    *,
    ctx,
    metric_name: str,
    spec: Dict[str, Any],
    filename: str | None,
) -> Dict[str, Any]:
    all_hits: List[Dict[str, Any]] = []

    for query in spec.get("queries", []):
        out = await hybrid_retrieve(
            ctx,
            query=query,
            limit=8,
            filename=filename,
        )

        if not isinstance(out, dict) or not out.get("ok"):
            continue

        hits = out.get("hits", []) or []
        all_hits.extend(hits)

    # 去重
    deduped: Dict[str, Dict[str, Any]] = {}
    for hit in all_hits:
        key = f"{hit.get('file_id')}::{hit.get('chunk_id')}"
        if key not in deduped:
            deduped[key] = hit

    return _pick_reason_from_hits(
        list(deduped.values()),
        must_keywords=spec.get("must", []),
        prefer_keywords=spec.get("prefer", []),
    )


async def extract_financial_reasons(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
    **kwargs,
) -> Dict[str, Any]:
    """
    RAG版原因抽取：
    1. 复用 Knowledge Runtime 的 chunk / embedding / hybrid_retrieve
    2. 每个财务指标单独检索
    3. 只从命中的原文 chunk 中摘取原因句
    4. 不让 LLM 自由生成原因，降低幻觉
    """
    inputs = state.get("collect_financial_inputs", {})
    filename = _resolve_reason_filename(state)

    specs = _reason_specs()
    reasons: Dict[str, Any] = {}

    for metric_name, spec in specs.items():
        result = await _retrieve_reason_for_metric(
            ctx=ctx,
            metric_name=metric_name,
            spec=spec,
            filename=filename,
        )

        if result.get("evidence"):
            reasons[metric_name] = result

    return {
        "ok": True,
        "reasons": reasons,
        "reason_count": len(reasons),
        "method": "rag_hybrid_retrieval",
        "filename": filename,
    }


async def verify_financial_reasons(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
    **kwargs,
) -> Dict[str, Any]:
    """
    强校验：
    reason 必须来自 evidence。
    """
    result = state.get("extract_financial_reasons", {})
    reasons = result.get("reasons", {}) if isinstance(result, dict) else {}

    verified: Dict[str, Any] = {}

    for metric_name, item in reasons.items():
        if not isinstance(item, dict):
            continue

        reason = str(item.get("reason", "")).strip()
        evidence = str(item.get("evidence", "")).strip()

        if not reason or not evidence:
            continue

        if reason == "材料中未体现。":
            continue

        compact_reason = re.sub(r"\s+", "", reason)
        compact_evidence = re.sub(r"\s+", "", evidence)

        if compact_reason in compact_evidence or compact_evidence in compact_reason:
            verified[metric_name] = item

    return {
        "ok": True,
        "reasons": verified,
        "reason_count": len(verified),
        "method": "evidence_substring_check",
    }