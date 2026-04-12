from pathlib import Path
import sqlite3

from app.core.document.parser_service import DocumentParserService

DB_PATH = Path("/home/sundasheng/p4_agent_sandbox/db/app.db")
ARTIFACTS_ROOT = Path("/home/sundasheng/p4_agent_sandbox/artifacts")
SANDBOX_ROOT = Path("/home/sundasheng/p4_agent_sandbox")

FILE_ID = "cf6f76a4bda74dc5"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
row = conn.execute(
    "SELECT file_id, filename, ext, rel_dir, raw_name FROM files WHERE file_id = ?",
    (FILE_ID,),
).fetchone()
conn.close()

if row is None:
    raise ValueError(f"file not found: {FILE_ID}")

raw_path = SANDBOX_ROOT / row["rel_dir"] / row["raw_name"]
print("raw_path =", raw_path)
print("exists   =", raw_path.exists())
print("filename =", row["filename"])
print("ext      =", row["ext"])

service = DocumentParserService(artifacts_root=ARTIFACTS_ROOT)

doc = service.parse_file(
    file_path=raw_path,
    file_id=row["file_id"],
    filename=row["filename"],
    ext=row["ext"],
    save=True,
)

print("\n=== parse result ===")
print("title      =", doc.title)
print("file_type  =", doc.file_type)
print("block_count=", doc.block_count)

for i, b in enumerate(doc.blocks[:10]):
    print(f"\n--- block #{i} ---")
    print("type       =", b.block_type)
    print("page_num   =", b.page_num)
    print("section    =", b.section_path)
    print("text       =", (b.text[:200] if b.text else ""))