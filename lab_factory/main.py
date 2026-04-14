import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, Inches
from docx.text.paragraph import Paragraph
from google import genai
from google.genai import types


BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

INLINE_PATTERN = re.compile(r"(\*\*.*?\*\*|\*.*?\*|`.*?`)")
LIST_ITEM_RE = re.compile(r"^\s*(\d+[\.\)]|[-•])\s+(.*)$")


# -----------------------------
# FILE READING
# -----------------------------
def read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def read_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_docx_file(path: Path) -> str:
    if not path.exists():
        return ""

    doc = Document(path)
    parts: List[str] = []

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            parts.append(text)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    parts.append(text)

    return "\n".join(parts).strip()


def extract_docx_headings(path: Path) -> List[str]:
    if not path.exists():
        return []

    doc = Document(path)
    headings: List[str] = []

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue

        style_name = ""
        try:
            style_name = paragraph.style.name.lower() if paragraph.style and paragraph.style.name else ""
        except Exception:
            style_name = ""

        if "heading" in style_name or "заголов" in style_name:
            headings.append(text)

    unique_headings: List[str] = []
    seen = set()
    for h in headings:
        if h not in seen:
            unique_headings.append(h)
            seen.add(h)

    return unique_headings


def find_first_nonempty_assignment_file() -> Optional[Path]:
    if not INPUT_DIR.exists():
        return None

    candidates = sorted(INPUT_DIR.glob("*.txt")) + sorted(INPUT_DIR.glob("*.docx"))
    ignored_names = {"notes.txt", "code.py", "meta.json"}

    for file in candidates:
        if file.name.lower() in ignored_names:
            continue

        if file.suffix.lower() == ".txt":
            text = read_text_file(file)
        elif file.suffix.lower() == ".docx":
            text = read_docx_file(file)
        else:
            continue

        if text.strip():
            return file

    return None


def read_assignment() -> Dict[str, object]:
    file_path = find_first_nonempty_assignment_file()

    if not file_path:
        return {
            "source_name": "",
            "text": "",
            "headings": []
        }

    if file_path.suffix.lower() == ".txt":
        text = read_text_file(file_path)
        headings = []
    else:
        text = read_docx_file(file_path)
        headings = extract_docx_headings(file_path)

    return {
        "source_name": file_path.name,
        "text": text,
        "headings": headings
    }


def find_signature_image() -> Optional[Path]:
    if not INPUT_DIR.exists():
        return None

    keywords = ["sign", "signature", "podpis", "подпис"]

    for file in sorted(INPUT_DIR.iterdir()):
        if file.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        lower_name = file.stem.lower()
        if any(k in lower_name for k in keywords):
            return file

    return None


# -----------------------------
# PROMPT / GEMINI
# -----------------------------
def build_prompt(
    assignment_text: str,
    detected_headings: List[str],
    notes: str,
    code_text: str,
    meta: Dict[str, Any]
) -> str:
    assignment_text = assignment_text[:14000]
    notes = notes[:5000]
    code_text = code_text[:8000]

    detected_headings_json = json.dumps(detected_headings, ensure_ascii=False)
    subject = str(meta.get("subject", "")).strip()

    code_instruction = ""
    if not code_text.strip():
        code_instruction = """
Если код программы не предоставлен, но по смыслу лабораторной он действительно нужен, сгенерируй короткий и понятный студенческий пример.
Не превращай код в огромный мини-проект.
Если вставляешь код, оформи его как отдельную секцию с заголовком "Листинг программы" или "Код программы".
"""

    return f"""
Ты помогаешь подготовить отчёт по лабораторной работе для Word-документа.

Контекст:
- Дисциплина: {subject if subject else "не указана"}
- Это именно отчёт по лабораторной работе, а не обзорная статья и не реферат.

Главные правила:
- Если в методичке явно заданы названия разделов, используй их.
- Если найдены заголовки документа, ориентируйся на них в первую очередь.
- Построй структуру так, чтобы отчёт был похож на обычную сдаваемую студенческую лабораторную работу.
- Пиши по делу.
- Не используй канцелярские фразы вроде "в рамках данной работы", "следует отметить", "данная работа посвящена".
- Не делай текст слишком энциклопедическим.
- Если для демонстрации не хватает примеров, входных данных или кратких пояснений, можешь привести разумный учебный пример.
- Не пиши "данных недостаточно", если можно нормально достроить черновик по теме.
- Не добавляй лишние разделы.

Форматирование:
- Не используй markdown-заголовки через #.
- Не используй тройные кавычки ``` .
- Можно использовать только inline-выделение:
  **жирный** — для важных терминов
  *курсив* — для отдельных названий
  `код` — для коротких формул, векторов, параметров и фрагментов кода

Списки:
- Если перечисляешь несколько пунктов, каждый пункт пиши с новой строки.
- Не склеивай нумерованные списки в один абзац.
- Для перечислений используй формат:
  1. ...
  2. ...
  3. ...

Структура:
- Верни иерархию разделов.
- У раздела могут быть подразделы.
- Если подразделы уместны, обязательно используй их.
- Особенно если в работе есть блоки вроде "Базы данных", "Калькулятор CVSS", "Отличия версий", "Вывод" и т.п.

{code_instruction}

Найденные заголовки:
{detected_headings_json}

[ТЕКСТ МЕТОДИЧКИ / ЗАДАНИЯ]
{assignment_text if assignment_text.strip() else "Не предоставлено"}

[ЗАМЕТКИ]
{notes if notes.strip() else "Нет"}

[КОД]
{code_text if code_text.strip() else "Не предоставлен"}

Верни СТРОГО валидный JSON формата:

{{
  "report_title": "название лабораторной работы",
  "sections": [
    {{
      "heading": "название раздела",
      "content": "текст раздела",
      "subsections": [
        {{
          "heading": "название подраздела",
          "content": "текст подраздела"
        }}
      ]
    }}
  ]
}}

Требования:
- Только JSON
- Без комментариев
- Без пояснений вне JSON
- Поле "subsections" можно делать пустым списком []
""".strip()


def generate_report_json_gemini(api_key: str, model_name: str, prompt: str) -> Dict:
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.35,
            response_mime_type="application/json"
        )
    )

    text = (response.text or "").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini вернул невалидный JSON:\n{text}") from e

    if not isinstance(data, dict):
        raise RuntimeError("Gemini вернул не JSON-объект.")

    if "sections" not in data or not isinstance(data["sections"], list):
        raise RuntimeError("В JSON нет поля 'sections' или оно не является списком.")

    normalize_sections(data["sections"])
    return data


def normalize_sections(sections: List[Dict[str, Any]]) -> None:
    for section in sections:
        if "heading" not in section:
            section["heading"] = ""
        if "content" not in section:
            section["content"] = ""
        if "subsections" not in section or not isinstance(section["subsections"], list):
            section["subsections"] = []

        for subsection in section["subsections"]:
            if "heading" not in subsection:
                subsection["heading"] = ""
            if "content" not in subsection:
                subsection["content"] = ""


# -----------------------------
# CLEANUP / PARSING
# -----------------------------
def cleanup_heading(text: str) -> str:
    text = text.replace("**", "").replace("*", "").replace("`", "")
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def cleanup_code_fences(text: str) -> str:
    if not text:
        return text

    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    return text


def split_into_paragraphs(text: str) -> List[str]:
    if not text.strip():
        return []

    lines = [line.rstrip() for line in text.splitlines()]

    result: List[str] = []
    buffer: List[str] = []

    def flush_buffer():
        nonlocal buffer
        if buffer:
            result.append(" ".join(x.strip() for x in buffer if x.strip()).strip())
            buffer = []

    list_item_pattern = re.compile(r"^\s*(\d+[\.\)]|[-•])\s+")
    heading_like_pattern = re.compile(r"^\s*\d+(\.\d+)*\.\s+")

    for line in lines:
        stripped = line.strip()

        if not stripped:
            flush_buffer()
            continue

        if list_item_pattern.match(stripped) or heading_like_pattern.match(stripped):
            flush_buffer()
            result.append(stripped)
            continue

        buffer.append(stripped)

    flush_buffer()
    return result


def parse_inline_list_items(text: str) -> List[str]:
    """
    Ловит:
    1. aaa 2. bbb 3. ccc
    И еще случай:
    ... используются три группы метрик:    Базовые метрики ...
    """
    raw = text.strip()
    normalized = re.sub(r"[ \t]+", " ", raw)

    # Классический склеенный нумерованный список
    matches = list(re.finditer(r"(?=(?:^|\s)(\d+)\.\s+)", normalized))
    if len(matches) >= 2:
        items = []
        for i, match in enumerate(matches):
            start = match.start()
            if start > 0 and normalized[start].isspace():
                start += 1
            end = matches[i + 1].start() if i + 1 < len(matches) else len(normalized)
            chunk = normalized[start:end].strip()
            if chunk:
                items.append(chunk)
        return items

    # Случай "Базовые метрики ... Временные метрики ... Контекстные метрики ..."
    metric_heads = [
        "Базовые метрики",
        "Временные метрики",
        "Контекстные метрики",
        "Base Metrics",
        "Temporal Metrics",
        "Environmental Metrics",
    ]

    positions = []
    for head in metric_heads:
        for m in re.finditer(re.escape(head), normalized):
            positions.append((m.start(), head))

    positions.sort(key=lambda x: x[0])

    if len(positions) >= 2:
        items = []
        for i, (start, _) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(normalized)
            chunk = normalized[start:end].strip(" :;")
            if chunk:
                items.append(f"• {chunk}")
        return items

    return []


def extract_code_from_sections(report_data: Dict) -> Optional[str]:
    code_like_titles = {
        "листинг программы",
        "код программы",
        "программа",
        "листинг",
        "исходный код"
    }

    sections = report_data.get("sections", [])
    cleaned_sections = []
    extracted_code = None

    for section in sections:
        heading = str(section.get("heading", "")).strip().lower()
        content = str(section.get("content", "")).strip()

        if heading in code_like_titles and content:
            extracted_code = cleanup_code_fences(content)
            continue

        sub_cleaned = []
        for subsection in section.get("subsections", []):
            sub_heading = str(subsection.get("heading", "")).strip().lower()
            sub_content = str(subsection.get("content", "")).strip()

            if sub_heading in code_like_titles and sub_content and not extracted_code:
                extracted_code = cleanup_code_fences(sub_content)
                continue

            sub_cleaned.append(subsection)

        section["subsections"] = sub_cleaned
        cleaned_sections.append(section)

    report_data["sections"] = cleaned_sections
    return extracted_code


# -----------------------------
# DOCX FORMATTING
# -----------------------------
def set_run_font(run, font_name: str = "Times New Roman", font_size: int = 14) -> None:
    run.font.name = font_name
    if run._element.rPr is None:
        run._element.get_or_add_rPr()
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
    run.font.size = Pt(font_size)


def apply_gost_style(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(3)
    section.right_margin = Cm(1.5)

    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(14)

    paragraph_format = style.paragraph_format
    paragraph_format.first_line_indent = Cm(1.25)
    paragraph_format.line_spacing = 1.5
    paragraph_format.space_before = Pt(0)
    paragraph_format.space_after = Pt(0)


def add_formatted_text(paragraph: Paragraph, text: str) -> None:
    parts = INLINE_PATTERN.split(text)

    for part in parts:
        if not part:
            continue

        if part.startswith("**") and part.endswith("**") and len(part) >= 4:
            content = part[2:-2]
            run = paragraph.add_run(content)
            run.bold = True
            set_run_font(run, "Times New Roman", 14)

        elif (
            part.startswith("*")
            and part.endswith("*")
            and len(part) >= 2
            and not (part.startswith("**") and part.endswith("**"))
        ):
            content = part[1:-1]
            run = paragraph.add_run(content)
            run.italic = True
            set_run_font(run, "Times New Roman", 14)

        elif part.startswith("`") and part.endswith("`") and len(part) >= 2:
            content = part[1:-1]
            run = paragraph.add_run(content)
            set_run_font(run, "Courier New", 11)

        else:
            run = paragraph.add_run(part)
            set_run_font(run, "Times New Roman", 14)


def add_list_item_paragraph(doc: Document, text: str) -> None:
    m = LIST_ITEM_RE.match(text.strip())
    if m:
        marker = m.group(1)
        content = m.group(2).strip()
    else:
        marker = "•"
        content = text.strip()
        if content.startswith("•"):
            content = content[1:].strip()

    p = doc.add_paragraph()
    p.style = doc.styles["Normal"]
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.left_indent = Cm(1.25)
    p.paragraph_format.line_spacing = 1.5

    run = p.add_run(f"{marker} ")
    set_run_font(run, "Times New Roman", 14)

    add_formatted_text(p, content)


def render_content_block(doc: Document, block: str) -> None:
    block = block.strip()
    if not block:
        return

    inline_items = parse_inline_list_items(block)
    if inline_items:
        for item in inline_items:
            add_list_item_paragraph(doc, item)
        return

    if LIST_ITEM_RE.match(block):
        add_list_item_paragraph(doc, block)
        return

    p = doc.add_paragraph()
    p.style = doc.styles["Normal"]
    p.paragraph_format.first_line_indent = Cm(1.25)
    p.paragraph_format.left_indent = Cm(0)
    p.paragraph_format.line_spacing = 1.5
    add_formatted_text(p, block)


def add_paragraph_text(doc: Document, text: str) -> None:
    for block in split_into_paragraphs(text):
        render_content_block(doc, block)


def add_heading_paragraph(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.first_line_indent = Cm(1.25)
    p.paragraph_format.left_indent = Cm(0)
    p.paragraph_format.line_spacing = 1.5

    run = p.add_run(text)
    run.bold = True
    set_run_font(run, "Times New Roman", 14)


def add_centered_bold_paragraph(doc: Document, text: str, font_size: int = 14, line_spacing: float = 1.0) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing = line_spacing

    run = p.add_run(text)
    run.bold = True
    set_run_font(run, "Times New Roman", font_size)


def add_table_of_contents(doc: Document) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.first_line_indent = Cm(0)

    run = p.add_run()
    set_run_font(run)

    fld_char_begin = OxmlElement("w:fldChar")
    fld_char_begin.set(qn("w:fldCharType"), "begin")

    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = 'TOC \\o "1-3" \\h \\z \\u'

    fld_char_separate = OxmlElement("w:fldChar")
    fld_char_separate.set(qn("w:fldCharType"), "separate")

    fld_char_end = OxmlElement("w:fldChar")
    fld_char_end.set(qn("w:fldCharType"), "end")

    run._r.append(fld_char_begin)
    run._r.append(instr_text)
    run._r.append(fld_char_separate)
    run._r.append(fld_char_end)


# -----------------------------
# TITLE PAGE
# -----------------------------
def add_title_page(doc: Document, meta: Dict[str, Any], report_title: str) -> None:
    university = str(meta.get("university", "")).strip()
    faculty = str(meta.get("faculty", "")).strip()
    subject = str(meta.get("subject", "")).strip()
    student_name = str(meta.get("student_name", "")).strip()
    group = str(meta.get("group", "")).strip()
    teacher = str(meta.get("teacher", "")).strip()
    city = str(meta.get("city", "")).strip()
    year = str(meta.get("year", "")).strip()

    signature_image = find_signature_image()

    lab_header = "ОТЧЕТ ПО ЛАБОРАТОРНОЙ РАБОТЕ"
    lab_topic = ""

    cleaned_title = report_title.strip()
    m = re.match(
        r"^\s*Лабораторная\s+работа\s*№\s*(\d+)\s*[:\-]?\s*(.*)$",
        cleaned_title,
        flags=re.IGNORECASE
    )
    if m:
        number = m.group(1).strip()
        tail = m.group(2).strip()
        lab_header = f"ОТЧЕТ ПО ЛАБОРАТОРНОЙ РАБОТЕ № {number}"
        lab_topic = tail
    else:
        lab_topic = cleaned_title

    if university:
        uni_lines = [line.strip() for line in university.split("\n") if line.strip()]
        for idx, line in enumerate(uni_lines):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.15

            run = p.add_run(line)
            run.bold = True
            set_run_font(run, "Times New Roman", 8 if idx == 0 else 12)

    if faculty:
        doc.add_paragraph()
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.15

        run = p.add_run(faculty)
        run.bold = True
        set_run_font(run, "Times New Roman", 12)

    for _ in range(6):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run("Дисциплина:")
    run.bold = True
    set_run_font(run, "Times New Roman", 12)

    if subject:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(f"«{subject}»")
        set_run_font(run, "Times New Roman", 12)

    for _ in range(4):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run(lab_header)
    run.bold = True
    set_run_font(run, "Times New Roman", 12)

    if lab_topic:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(f"«{lab_topic}»")
        set_run_font(run, "Times New Roman", 12)

    for _ in range(6):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run("Выполнил:")
    run.bold = True
    set_run_font(run, "Times New Roman", 12)

    if group:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(f"Студент гр. {group}")
        set_run_font(run, "Times New Roman", 12)

    if student_name:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(student_name)
        set_run_font(run, "Times New Roman", 12)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run("Подпись:")
    set_run_font(run, "Times New Roman", 12)

    if signature_image:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.0
        run = p.add_run()
        run.add_picture(str(signature_image), height=Cm(1.5))

    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run("Проверил:")
    run.bold = True
    set_run_font(run, "Times New Roman", 12)

    if teacher:
        teacher_lines = [line.strip() for line in teacher.split("\n") if line.strip()]
        for line in teacher_lines:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.15
            run = p.add_run(line)
            set_run_font(run, "Times New Roman", 12)

    for _ in range(7):
        doc.add_paragraph()

    footer = ""
    if city and year:
        footer = f"{city}\n{year}г."
    elif city:
        footer = city
    elif year:
        footer = f"{year}г."

    if footer:
        for line in footer.split("\n"):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.15
            run = p.add_run(line)
            set_run_font(run, "Times New Roman", 12)

    doc.add_page_break()


# -----------------------------
# BODY RENDERING
# -----------------------------
def render_sections(doc: Document, sections: List[Dict[str, Any]]) -> None:
    for i, section in enumerate(sections, start=1):
        heading = cleanup_heading(str(section.get("heading", "")).strip())
        content = str(section.get("content", "")).strip()
        subsections = section.get("subsections", [])

        if heading:
            add_heading_paragraph(doc, f"{i}. {heading}")

        if content:
            add_paragraph_text(doc, content)

        for j, subsection in enumerate(subsections, start=1):
            sub_heading = cleanup_heading(str(subsection.get("heading", "")).strip())
            sub_content = str(subsection.get("content", "")).strip()

            if sub_heading:
                add_heading_paragraph(doc, f"{i}.{j}. {sub_heading}")

            if sub_content:
                add_paragraph_text(doc, sub_content)


def add_code_section(doc: Document, code_text: str) -> None:
    if not code_text.strip():
        return

    doc.add_page_break()
    add_heading_paragraph(doc, "Приложение А. Листинг программы")

    code_text = cleanup_code_fences(code_text)

    for line in code_text.splitlines():
        p = doc.add_paragraph()
        p.style = doc.styles["Normal"]
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.left_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.0

        run = p.add_run(line if line else " ")
        set_run_font(run, "Courier New", 10)


def add_images_from_input(doc: Document) -> None:
    if not INPUT_DIR.exists():
        return

    signature_image = find_signature_image()
    images = []
    for file in sorted(INPUT_DIR.iterdir()):
        if file.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if signature_image and file.resolve() == signature_image.resolve():
            continue
        images.append(file)

    if not images:
        return

    doc.add_page_break()
    add_heading_paragraph(doc, "Приложение Б. Иллюстрации")

    for idx, image_path in enumerate(images, start=1):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)

        run = p.add_run()
        run.add_picture(str(image_path), width=Inches(5.8))

        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.first_line_indent = Cm(0)

        caption = f"Рисунок {idx} — {image_path.stem}"
        run = cap.add_run(caption)
        set_run_font(run, "Times New Roman", 12)


def create_docx(report_data: Dict, code_text: str, meta: Dict[str, Any], output_path: Path) -> None:
    doc = Document()
    apply_gost_style(doc)

    report_title = str(report_data.get("report_title", "Лабораторная работа")).strip()

    add_title_page(doc, meta, report_title)

    add_heading_paragraph(doc, "Содержание")
    add_table_of_contents(doc)
    doc.add_page_break()

    sections = report_data.get("sections", [])
    render_sections(doc, sections)

    if code_text.strip():
        add_code_section(doc, code_text)

    add_images_from_input(doc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)


# -----------------------------
# MAIN
# -----------------------------
def generate_lab_report_from_dirs(input_dir: Path, output_dir: Path) -> Path:
    load_dotenv()

    global INPUT_DIR, OUTPUT_DIR
    old_input, old_output = INPUT_DIR, OUTPUT_DIR

    INPUT_DIR = Path(input_dir)
    OUTPUT_DIR = Path(output_dir)

    try:
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        if not gemini_api_key:
            raise RuntimeError("Не найден GEMINI_API_KEY в .env")

        meta = read_json_file(INPUT_DIR / "meta.json")

        assignment_data = read_assignment()
        assignment_text = str(assignment_data.get("text", "")).strip()
        detected_headings = assignment_data.get("headings", [])

        notes = read_text_file(INPUT_DIR / "notes.txt")
        code_text = read_text_file(INPUT_DIR / "code.py")

        if not assignment_text and not notes and not code_text:
            raise RuntimeError("Нет данных для генерации отчёта")

        prompt = build_prompt(
            assignment_text=assignment_text,
            detected_headings=detected_headings,
            notes=notes,
            code_text=code_text,
            meta=meta
        )

        report_data = generate_report_json_gemini(
            api_key=gemini_api_key,
            model_name=gemini_model,
            prompt=prompt
        )

        if not code_text.strip():
            extracted_code = extract_code_from_sections(report_data)
            if extracted_code:
                code_text = extracted_code

        output_docx = OUTPUT_DIR / "lab_report.docx"

        create_docx(
            report_data=report_data,
            code_text=code_text,
            meta=meta,
            output_path=output_docx
        )

        return output_docx

    finally:
        INPUT_DIR = old_input
        OUTPUT_DIR = old_output

def main() -> None:
    output_docx = generate_lab_report_from_dirs(INPUT_DIR, OUTPUT_DIR)
    print(f"Готово: {output_docx}")

if __name__ == "__main__":
    main()
