from pathlib import Path
from unstructured.partition.pdf import partition_pdf

pdf_path = Path("/home/sundasheng/p4_agent_sandbox/uploads/cf6f76a4bda74dc5/raw.pdf")

elements = partition_pdf(
    filename=str(pdf_path),
    strategy="fast",   # 对普通文本型 PDF 先用 fast
)

print("element_count =", len(elements))
print()

for i, el in enumerate(elements[:20]):
    text = getattr(el, "text", "") or ""
    print(f"--- element #{i} ---")
    print("type =", el.__class__.__name__)
    print("text =", text[:200].replace("\n", " "))
    print()