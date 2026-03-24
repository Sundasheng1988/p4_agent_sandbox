# file_service
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Dict, Any

from app.core.audit import AuditLogger
from app.core.storage import TaskStore


class FileService:
    def __init__(self, sandbox_root: str, store: TaskStore, audit: AuditLogger):
        self.sandbox_root = os.path.abspath(os.path.expanduser(sandbox_root))
        self.uploads_root = os.path.join(self.sandbox_root, "uploads")
        self.store = store
        self.audit = audit
        os.makedirs(self.uploads_root, exist_ok=True)

    def _sha256(self, data: bytes) -> str:
        h = hashlib.sha256()
        h.update(data)
        return h.hexdigest()

    async def save_upload(self, filename: str, mime: str, data: bytes) -> Dict[str, Any]:
        file_id = uuid.uuid4().hex[:16]
        created_at = time.time()

        ext = Path(filename).suffix.lower().lstrip(".") or "bin"
        raw_name = f"raw.{ext}"

        rel_dir = os.path.join("uploads", file_id)
        abs_dir = os.path.join(self.sandbox_root, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)

        sha256 = self._sha256(data)
        size = len(data)

        raw_path = os.path.join(abs_dir, raw_name)
        meta_path = os.path.join(abs_dir, "meta.json")

        with open(raw_path, "wb") as f:
            f.write(data)

        meta = {
            "file_id": file_id,
            "filename": filename,
            "mime": mime,
            "ext": ext,
            "size": size,
            "sha256": sha256,
            "rel_dir": rel_dir,
            "raw_name": raw_name,
            "created_at": created_at,
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        await self.store.upsert_file(meta)

        # 用 file_id 当 trace_id，便于追溯“文件怎么来的”
        self.audit.write(file_id, "file_upload", meta)

        return meta
    
    def _file_dir(self, file_id: str) -> str:
        # uploads/<file_id>/
        return os.path.join(self.uploads_root, file_id)

    def _raw_path(self, file_id: str) -> str:
        # 读 meta.json 以拿到 raw_name（兼容 raw.txt / raw.pdf 等）
        meta_path = os.path.join(self._file_dir(file_id), "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            raw_name = meta.get("raw_name") or "raw.txt"
        else:
            # fallback：历史数据或异常情况
            raw_name = "raw.txt"
        return os.path.join(self._file_dir(file_id), raw_name)

    async def read_text_by_id(self, file_id: str, max_bytes: int = 200000) -> Dict[str, Any]:
        raw_path = self._raw_path(file_id)
        if not os.path.exists(raw_path):
            raise FileNotFoundError(raw_path)

        with open(raw_path, "rb") as f:
            data = f.read(max_bytes)

        # 先按 utf-8 解码（errors=replace 确保不炸）
        text = data.decode("utf-8", errors="replace")

        return {"file_id": file_id, "text": text}
    
    def _strip_gutenberg_header_footer(self, text: str) -> str:
        t = text or ""
        t = t.replace("\r\n", "\n").replace("\r", "\n")

        start_pat = re.compile(
            r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
            re.IGNORECASE,
        )
        end_pat = re.compile(
            r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
            re.IGNORECASE,
        )

        m1 = start_pat.search(t)
        if m1:
            t = t[m1.end():]

        m2 = end_pat.search(t)
        if m2:
            t = t[: m2.start()]

        return t.strip()

    def _remove_toc_block(self, text: str) -> str:
        t = text or ""
        lines = [ln.rstrip() for ln in t.splitlines()]

        idx_contents = None
        for i, ln in enumerate(lines[:2000]):
            if ln.strip().lower() in ("contents", "table of contents"):
                idx_contents = i
                break

        if idx_contents is None:
            return t.strip()

        chap_pat = re.compile(r"^\s*chapter\s+[0-9ivxlcdm]+\b", re.IGNORECASE)

        def looks_like_body(ln: str) -> bool:
            s = ln.strip()
            if len(s) < 40:
                return False
            if " " not in s:
                return False
            if s.isupper():
                return False
            return True

        first_chap = None
        for j in range(idx_contents, min(len(lines), idx_contents + 1200)):
            if chap_pat.match(lines[j]):
                first_chap = j
                break

        if first_chap is None:
            return "\n".join(lines[idx_contents + 1 :]).strip()

        for k in range(first_chap, min(len(lines), first_chap + 1200)):
            if chap_pat.match(lines[k]):
                for p in range(k, min(len(lines), k + 200)):
                    if looks_like_body(lines[p]):
                        return "\n".join(lines[p:]).strip()

        return "\n".join(lines[idx_contents + 1 :]).strip()
    
    def _skip_leading_chapter_list(self, text: str) -> str:
        """
        如果文本开头是一串 CHAPTER 标题（目录/章节列表），跳到第一段正文。
        适配 Gutenberg 常见结构：CHAPTER I/II... 然后才出现正文段落。
        """
        t = text or ""
        lines = [ln.rstrip() for ln in t.splitlines()]

        chap_pat = re.compile(r"^\s*chapter\s+[0-9ivxlcdm]+\b", re.IGNORECASE)

        # 只在“开头区域”做处理，避免误伤正文中的 chapter 引用
        head = lines[:1500]

        # 如果开头区域 chapter 行占比很高，就认为这是目录/章节列表
        chap_lines = [i for i, ln in enumerate(head) if chap_pat.match(ln)]
        if len(chap_lines) < 3:
            return t.strip()

        # 从第一个 chapter 行开始往后找“正文句子”
        def looks_like_body(ln: str) -> bool:
            s = ln.strip()
            if len(s) < 60:
                return False
            # 正文一般有空格/标点，不是全大写
            if s.isupper():
                return False
            if " " not in s:
                return False
            return True

        start_i = chap_lines[0]
        for i in range(start_i, min(len(lines), start_i + 2000)):
            if looks_like_body(lines[i]):
                return "\n".join(lines[i:]).strip()

        # 找不到就保守返回原文
        return t.strip()

    def _normalize_whitespace(self, text: str) -> str:
        t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()

    def _extract_body_window(self, text: str) -> str:
        t = self._strip_gutenberg_header_footer(text)
        t = self._remove_toc_block(t)
        t = self._skip_leading_chapter_list(t)   # ✅ 新增这一行
        t = self._normalize_whitespace(t)
        return t

    async def parse_text_by_id(
        self,
        file_id: str,
        max_chars: int = 20000,
        max_bytes: int = 200000,
    ) -> Dict[str, Any]:
        # M2-1 baseline：先只支持 “text-first”，pdf/docx 后面再接你已有的 parse 工具或库
        out = await self.read_text_by_id(file_id=file_id, max_bytes=max_bytes)
        text = out.get("text") or ""
        # ✅ M2-1.1 正文抽取
        text = self._extract_body_window(text)

        # 🔎 DEBUG 标识：确认是否走到新 parse 逻辑
        # text = "[PARSE_V2_OK]\n" + text

        if len(text) > max_chars:
            text = text[:max_chars]

        return {"file_id": file_id, "text": text}
