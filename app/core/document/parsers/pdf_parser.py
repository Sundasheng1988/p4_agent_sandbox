from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

from app.core.document.normalizer import normalize_document
from app.core.document.parsers.base import BaseDocumentParser
from app.core.document.schema import DocumentBlock, ParsedDocument


_NOISE_KEYWORDS = [
    "中图法分类号",
    "文献标识码",
    "文章编号",
    "论文引用格式",
    "收稿日期",
    "修回日期",
    "预印本日期",
    "基金项目",
    "supported by",
    "通信作者",
]

_SECTION_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*|[零一二三四五六七八九十]+|[A-Z])\s*[\.．、]\s*.+$"
)
_SIMPLE_SECTION_RE = re.compile(r"^\d+(?:\.\d+)*\s+.+$")
_PURE_PAGE_NUM_RE = re.compile(r"^\d{1,4}$")
_DOI_RE = re.compile(r"\b10\.\s*\d{4,9}\b", re.IGNORECASE)
_VOL_ISSUE_RE = re.compile(
    r"(?:Vol\.?\s*\d+|第\s*\d+\s*卷|No\.?\s*\d+|第\s*\d+\s*期|20\d{2}\s*年\s*\d+\s*月)",
    re.IGNORECASE,
)


class PdfParser(BaseDocumentParser):
    def parse(self, file_path: Path, file_id: str, filename: str) -> ParsedDocument:
        pdf = fitz.open(str(file_path))
        blocks: List[DocumentBlock] = []
        order = 0
        section_stack: List[str] = []
        inferred_title: Optional[str] = None

        def next_block_id() -> str:
            return f"{file_id}_b{len(blocks):04d}"

        try:
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                page_num = page_index + 1

                page_items = self._extract_sorted_items(page)
                page_items = self._filter_page_noise(page_items, page_num)

                for item in page_items:
                    block_type = item["block_type"]
                    text = item["text"]
                    meta = item["meta"]

                    if not text and block_type != "image":
                        continue

                    if block_type == "image":
                        blocks.append(
                            DocumentBlock(
                                block_id=next_block_id(),
                                block_type="image",
                                text="[IMAGE]",
                                order=order,
                                page_num=page_num,
                                section_path=list(section_stack),
                                meta=meta,
                            )
                        )
                        order += 1
                        continue

                    if page_num == 1 and inferred_title is None:
                        maybe_title = self._is_likely_title(text)
                        if maybe_title:
                            inferred_title = text

                    is_heading, level = self._is_heading_block(text, page_num=page_num)
                    if is_heading:
                        level = max(1, level)
                        section_stack = section_stack[: max(level - 1, 0)]
                        section_stack.append(text)

                        blocks.append(
                            DocumentBlock(
                                block_id=next_block_id(),
                                block_type="heading",
                                text=text,
                                order=order,
                                level=level,
                                page_num=page_num,
                                section_path=list(section_stack),
                                meta=meta,
                            )
                        )
                        order += 1
                    else:
                        para_type = "list" if self._looks_like_list_block(text) else "paragraph"
                        blocks.append(
                            DocumentBlock(
                                block_id=next_block_id(),
                                block_type=para_type,
                                text=text,
                                order=order,
                                page_num=page_num,
                                section_path=list(section_stack),
                                meta=meta,
                            )
                        )
                        order += 1

            final_title = self._infer_title_from_blocks(blocks) or inferred_title or filename

            parsed = ParsedDocument(
                file_id=file_id,
                filename=filename,
                file_type="pdf",
                title=final_title,
                blocks=blocks,
                meta={"page_count": len(pdf)},
            )
            return normalize_document(parsed)
        finally:
            pdf.close()

    def _extract_sorted_items(self, page: fitz.Page) -> List[dict]:
        text_dict = page.get_text("dict")
        raw_blocks = text_dict.get("blocks", [])
        items: List[dict] = []

        sortable = []
        for block in raw_blocks:
            bbox = block.get("bbox", [0, 0, 0, 0])
            x0 = float(bbox[0]) if len(bbox) >= 1 else 0.0
            y0 = float(bbox[1]) if len(bbox) >= 2 else 0.0
            sortable.append((round(y0, 1), round(x0, 1), block))

        sortable.sort(key=lambda x: (x[0], x[1]))

        for _, _, block in sortable:
            bbox = block.get("bbox", [0, 0, 0, 0])
            meta = {"bbox": bbox}

            if block.get("type") == 1:
                items.append(
                    {
                        "block_type": "image",
                        "text": "[IMAGE]",
                        "meta": meta,
                    }
                )
                continue

            if block.get("type") != 0:
                continue

            text = self._extract_text_from_text_block(block)
            text = self._normalize_block_text(text)
            if not text:
                continue

            items.append(
                {
                    "block_type": "text",
                    "text": text,
                    "meta": meta,
                }
            )

        return items

    def _extract_text_from_text_block(self, block: dict) -> str:
        lines: List[str] = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            line_text = "".join(span.get("text", "") for span in spans).strip()
            if line_text:
                lines.append(line_text)
        return "\n".join(lines).strip()

    def _normalize_block_text(self, text: str) -> str:
        text = text.replace("\u00a0", " ")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _filter_page_noise(self, items: List[dict], page_num: int) -> List[dict]:
        filtered: List[dict] = []

        for item in items:
            if item["block_type"] != "text":
                filtered.append(item)
                continue

            text = item["text"].strip()
            if not text:
                continue

            if self._is_page_number_only(text):
                continue

            if self._is_running_header_footer(text):
                continue

            if page_num == 1 and self._is_first_page_noise(text):
                continue

            filtered.append(item)

        return filtered

    def _is_page_number_only(self, text: str) -> bool:
        stripped = text.strip()
        return bool(_PURE_PAGE_NUM_RE.fullmatch(stripped))

    def _is_running_header_footer(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True

        if _VOL_ISSUE_RE.search(stripped) and len(stripped) <= 40:
            return True

        author_line_markers = ["陈妍妍", "田大新", "林椿眄", "殷鸿博"]
        if sum(1 for name in author_line_markers if name in stripped) >= 2 and len(stripped) <= 40:
            return True

        return False

    def _is_first_page_noise(self, text: str) -> bool:
        lowered = text.lower()
        if any(k.lower() in lowered for k in _NOISE_KEYWORDS):
            return True

        if _DOI_RE.search(text):
            return True

        if "doi" in lowered:
            return True

        if "journal of image and graphics" in lowered:
            return True

        if "beihang university" in lowered and len(text) > 40:
            return False

        return False

    def _is_likely_title(self, text: str) -> bool:
        stripped = text.strip()

        if not stripped:
            return False
        if self._is_page_number_only(stripped):
            return False
        if self._is_first_page_noise(stripped):
            return False
        if self._is_running_header_footer(stripped):
            return False
        if _DOI_RE.search(stripped):
            return False
        if "\n" in stripped:
            return False

        # 长度限制更严格
        if len(stripped) < 6 or len(stripped) > 30:
            return False

        # 必须包含中文
        if not re.search(r"[\u4e00-\u9fff]", stripped):
            return False

        # 排除明显不是标题的内容
        bad_keywords = [
            "摘要",
            "关键词",
            "北京航空航天大学",
            "本文首先",
            "本文",
            "研究工作",
            "关键问题",
            "作者简介",
            "通信作者",
        ]
        if any(k in stripped for k in bad_keywords):
            return False

        # 不能像一句完整正文
        if stripped.endswith(("。", "；", "，", "：")):
            return False

        return True

    def _is_heading_block(self, text: str, page_num: int) -> tuple[bool, int]:
        stripped = text.strip()

        if not stripped:
            return False, 1
        if self._is_page_number_only(stripped):
            return False, 1
        if self._is_running_header_footer(stripped):
            return False, 1
        if page_num == 1 and self._is_first_page_noise(stripped):
            return False, 1
        if _DOI_RE.search(stripped):
            return False, 1
        if len(stripped) <= 6 and re.fullmatch(r"[\d\W]+", stripped):
            return False, 1
        if len(stripped) > 120:
            return False, 1

        # 中文论文首页标题
        if page_num == 1 and self._is_likely_title(stripped):
            return True, 1

        strong_titles = [
            "引言",
            "结语",
            "参考文献",
            "作者简介",
        ]
        if stripped in strong_titles:
            return True, 1

        # 摘要 / 关键词 不作为 heading，避免污染 section_path
        if stripped.startswith("摘要") or stripped.startswith("关键词"):
            return False, 1

        # 标准章节号：1 模块化系统架构 / 1.1 环境感知 / 2.3.1 BEV表征
        if _SECTION_HEADING_RE.match(stripped) or _SIMPLE_SECTION_RE.match(stripped):
            return True, self._infer_heading_level_from_numbering(stripped)

        # 特判：0 引言 / 1 模块化系统架构
        if re.match(r"^\d+\s*[\u4e00-\u9fffA-Za-z].+", stripped):
            return True, self._infer_heading_level_from_numbering(stripped)

        return False, 1

    def _infer_heading_level_from_numbering(self, text: str) -> int:
        match = re.match(r"^(\d+(?:\.\d+)*)", text.strip())
        if not match:
            return 1
        numbering = match.group(1)
        return numbering.count(".") + 1

    def _looks_like_list_block(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return False

        hit = 0
        for line in lines:
            if line.startswith(("- ", "* ", "+ ", "• ", "● ", "（1）", "(1)")):
                hit += 1
                continue
            if re.match(r"^\d+[.)]\s+", line):
                hit += 1
                continue
            if re.match(r"^（\d+）", line):
                hit += 1
                continue

        return hit >= max(1, len(lines) // 2)
    
    def _infer_title_from_blocks(self, blocks: List[DocumentBlock]) -> Optional[str]:
        candidates: List[str] = []

        for b in blocks[:30]:
            if b.page_num != 1:
                continue
            if b.block_type != "paragraph" and b.block_type != "heading":
                continue

            text = (b.text or "").strip()
            if not text:
                continue
            if not re.search(r"[\u4e00-\u9fff]", text):
                continue
            if len(text) < 6 or len(text) > 30:
                continue
            if text.endswith(("。", "；", "，", "：")):
                continue

            bad_keywords = [
                "摘要",
                "关键词",
                "北京航空航天大学",
                "本文首先",
                "本文",
                "研究工作",
                "关键问题",
                "作者简介",
                "通信作者",
            ]
            if any(k in text for k in bad_keywords):
                continue

            candidates.append(text)

        if not candidates:
            return None

        # 优先选最短且像标题的
        candidates.sort(key=lambda x: (len(x), x))
        return candidates[0]