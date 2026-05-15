# rag_reasoner.py
from __future__ import annotations

from typing import Any, Dict, List

from app.core.rag_pipeline import run_rag_pipeline


FINANCIAL_RAG_QUERIES = {
    "company_profile": {
        "retrieval_query": "报告期内公司从事的主要业务 主营业务 输配电设备 主要产品",
        "question": "请概括公司的主营业务、主要产品和业务结构。",
        "prefer_text": True,
        "section_type": "management_discussion",
        "financial_topic": "management_discussion",
    },
    "revenue": {
        "retrieval_query": "营业收入 同比增长 国内营业收入 海外市场 营业收入 分产品 分地区",
        "question": "请提取并整理公司营业收入增长、收入来源、分产品和分地区表现的原文证据。",
        "prefer_text": False,
        "section_type": "business_analysis",
        "financial_topic": "revenue",
    },
    "profit": {
        "retrieval_query": "净利润 毛利率 费用 研发费用 销售费用 管理费用 财务费用 盈利能力",
        "question": "请提取并整理公司利润、毛利率、费用和盈利能力变化的原文证据。",
        "prefer_text": False,
        "section_type": "business_analysis",
        "financial_topic": "profit",
    },
    "cashflow": {
        "retrieval_query": "现金流 经营活动产生的现金流量净额 投资活动 筹资活动 现金流同比",
        "question": "请提取并整理公司经营现金流、投资现金流、筹资现金流变化及原因的原文证据。",
        "prefer_text": False,
        "section_type": "business_analysis",
        "financial_topic": "cashflow",
    },
    "balance_sheet": {
        "retrieval_query": "资产构成重大变动情况 货币资金 应收账款 存货 合同资产 预付款项 应付账款 重大变动说明",
        "question": "请提取并整理公司资产负债结构和主要资产负债项目变动原因的原文证据。",
        "prefer_text": False,
        "section_type": "balance_sheet_analysis",
        "financial_topic": "balance_sheet",
    },
    "segments": {
        "retrieval_query": "分行业 分产品 分地区 开关类业务 变压器类业务 储能系统及元件类业务 海外地区",
        "question": "请提取并整理公司分产品、分行业、分地区经营表现的原文证据。",
        "prefer_text": False,
        "section_type": "business_analysis",
        "financial_topic": "revenue",
    },
    "growth_drivers": {
        "retrieval_query": (
            "全球化战略 海外根据地 新兴赛道 增长引擎 特高压 超高压 "
            "变压器 GIS 储能 构网型 技术创新 研发投入"
        ),
        "question": "请提取并整理公司增长驱动因素的原文证据，包括全球化、新兴赛道、技术研发和产品布局。",
        "prefer_text": True,
        "section_type": "future_outlook",
        "financial_topic": "management_discussion",
    },
    "risks": {
        "retrieval_query": "公司面临的风险及应对措施 市场风险 汇率风险 税务风险 应收账款风险 合同风险 工程分包风险",
        "question": "请提取并整理公司披露的主要风险因素及应对措施的原文证据。",
        "prefer_text": True,
        "section_type": "risk_analysis",
        "financial_topic": "risks",
    },
    "management_discussion": {
        "retrieval_query": "经营目标完成情况 未来发展的展望 经营计划 经营目标 管理层讨论与分析",
        "question": "请提取并整理管理层讨论与分析中的经营情况和未来展望原文证据。",
        "prefer_text": True,
        "section_type": "future_outlook",
        "financial_topic": "management_discussion",
    },
}


def _is_table_hit(hit: Dict[str, Any]) -> bool:
    chunk_id = str(hit.get("chunk_id") or "")
    snippet = str(hit.get("snippet") or "")

    if "_table_" in chunk_id:
        return True

    if snippet.startswith("表格来源："):
        return True

    return False


def _filter_hits_for_section(
    hits: List[Dict[str, Any]],
    *,
    prefer_text: bool,
    min_keep: int = 3,
) -> List[Dict[str, Any]]:
    if not hits:
        return []

    if not prefer_text:
        return hits

    text_hits = [h for h in hits if not _is_table_hit(h)]

    if len(text_hits) >= min_keep:
        return text_hits

    if text_hits:
        text_ids = {id(h) for h in text_hits}
        fallback_hits = [h for h in hits if id(h) not in text_ids]
        return text_hits + fallback_hits[: max(0, min_keep - len(text_hits))]

    return hits


async def analyze_financial_with_rag(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
    model_name: str = "",
) -> Dict[str, Any]:
    inputs = state.get("collect_financial_inputs", {})
    file_id = inputs.get("file_id")
    filename = inputs.get("filename")

    results: Dict[str, Any] = {}
    has_valid_answer = False

    top_k = int(step.get("top_k", 8))
    max_context_chars = int(step.get("max_context_chars", 8000))
    skip_llm = bool(step.get("skip_llm", False))
    rag_model_name = step.get("model_name") or model_name or "qwen2.5:7b-instruct"

    for section, item in FINANCIAL_RAG_QUERIES.items():
        llm_sections = set(step.get("llm_sections") or [])

        section_skip_llm = skip_llm
        if llm_sections:
            section_skip_llm = section not in llm_sections

        retrieval_query = item["retrieval_query"]
        user_question = item["question"]
        prefer_text = bool(item.get("prefer_text", False))
        section_type = item.get("section_type")
        financial_topic = item.get("financial_topic")

        rag_question = retrieval_query
        retrieval_top_k = 3 if not section_skip_llm else (min(max(top_k * 2, 12), 50) if prefer_text else min(top_k, 50))

        rag_out = await run_rag_pipeline(
            ctx=ctx,
            sandbox_root=sandbox_root,
            question=rag_question,
            model_name=rag_model_name,
            top_k=retrieval_top_k,
            max_context_chars=max_context_chars,
            domains=None,
            file_type=step.get("file_type"),
            source=step.get("source"),
            file_id=file_id,
            query_understanding_model="qwen2.5:7b-instruct",
            use_query_understanding_llm=False,
            skip_llm=section_skip_llm,
            exclude_table_chunks=prefer_text,
            section_type=section_type,
            financial_topic=financial_topic,
        )

        raw_hits = rag_out.get("hits", []) or []
        filtered_hits = _filter_hits_for_section(
            raw_hits,
            prefer_text=prefer_text,
            min_keep=3,
        )

        answer = str(rag_out.get("answer") or "").strip()
        error = rag_out.get("error")

        if answer and "未在知识库中找到明确答案" not in answer and not error:
            has_valid_answer = True

        results[section] = {
            "file_id": file_id,
            "filename": filename,
            "retrieval_query": retrieval_query,
            "question": user_question,
            "prefer_text": prefer_text,
            "section_type": section_type,
            "financial_topic": financial_topic,

            "answer": answer,

            # 过滤后的 hits：给报告和调试优先使用
            "hits": filtered_hits,
            "hits_count": len(filtered_hits),

            # 原始 hits：保留方便对比
            "raw_hits": raw_hits,
            "raw_hits_count": len(raw_hits),

            "error": error,
            "retrieval_mode": rag_out.get("retrieval_mode"),
            "retrieval_queries": rag_out.get("retrieval_queries"),
            "effective_queries": rag_out.get("effective_queries"),
            "domains": rag_out.get("domains"),
            "router_notes": rag_out.get("router_notes"),
            "routing_reason": rag_out.get("routing_reason"),
            "context_preview": str(rag_out.get("context", "") or "")[:1200],
            "skip_llm": rag_out.get("skip_llm"),
            "llm_model": rag_out.get("llm_model"),
            "query_understanding_model": rag_out.get("query_understanding_model"),
            "use_query_understanding_llm": rag_out.get("use_query_understanding_llm"),

            "section_skip_llm": section_skip_llm,
            
        }

    return {
        "ok": True,
        "analysis": results,
        "has_valid_answer": has_valid_answer,
    }