
import os
import re
import sqlite3

import pdfplumber
from docx import Document
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DATABASE = os.path.join(BASE_DIR, "resumes.db")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

ALLOWED_EXTENSIONS = {"pdf", "docx"}

# Install the model using:
# python -m spacy download en_core_web_sm


SKILLS_LIST = [
    "Python", "Java", "C++", "C", "SQL", "PostgreSQL",
    "Machine Learning", "Deep Learning", "Data Analysis",
    "HTML", "CSS", "JavaScript", "Flask", "Django",
    "TensorFlow", "PyTorch", "Excel", "MATLAB",
    "Communication", "Problem Solving"
]


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                phone TEXT,
                education TEXT,
                skills TEXT,
                filename TEXT
            )
        """)


def extract_text(filepath):
    extension = filepath.rsplit(".", 1)[-1].lower()

    if extension == "pdf":
        with pdfplumber.open(filepath) as pdf:
            return "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )

    if extension == "docx":
        document = Document(filepath)
        paragraphs = [
            paragraph.text for paragraph in document.paragraphs
        ]

        # Include text in tables, which many resumes use.
        for table in document.tables:
            for row in table.rows:
                paragraphs.extend(cell.text for cell in row.cells)

        return "\n".join(paragraphs)

    raise ValueError("Unsupported file type")


def extract_information(text):
    email_match = re.search(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        text
    )
    email = email_match.group(0) if email_match else ""

    phone_match = re.search(
        r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)",
        text
    )
    phone = phone_match.group(0).strip() if phone_match else ""

    # Basic name detection without spaCy
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    name = ""

    excluded_headings = re.compile(
        r"^(resume|curriculum vitae|cv|contact|"
        r"education|skills|experience|profile|"
        r"projects|summary)$",
        re.IGNORECASE 
    )

    for line in lines[:10]:
        candidate = re.sub(r"\s+", " ", line).strip()

        if (
            2 <= len(candidate.split()) <= 4
            and not re.search(r"\d|@", candidate)
            and not excluded_headings.fullmatch(candidate)
            and re.fullmatch(r"[A-Za-z .'-]+", candidate)
        ):
            name = candidate 
            break 
        

    # Match known skills without depending on capitalization
    text_lower = text.lower()
    skills = [
        skill for skill in SKILLS_LIST
        if re.search(
            r"(?<!\w)" + re.escape(skill.lower()) + r"(?!\w)",
            text_lower
        )
    ]

    # Basic education-section extraction
    education = ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for index, line in enumerate(lines):
        if re.search(r"\beducation\b", line, re.IGNORECASE):
            education = " | ".join(lines[index + 1:index + 5])
            break

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "education": education,
        "skills": ", ".join(skills)
    }


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        uploaded_file = request.files.get("resume")

        if not uploaded_file or not uploaded_file.filename:
            flash("Please select a resume.")
            return redirect(url_for("index"))

        safe_name = secure_filename(uploaded_file.filename)
        extension = safe_name.rsplit(".", 1)[-1].lower()

        if extension not in ALLOWED_EXTENSIONS:
            flash("Only PDF and DOCX files are supported.")
            return redirect(url_for("index"))

        # Randomized filename prevents simple filename collisions.
        import uuid
        stored_name = f"{uuid.uuid4().hex}.{extension}"
        filepath = os.path.join(UPLOAD_FOLDER, stored_name)

        try:
            uploaded_file.save(filepath)
            text = extract_text(filepath)

            if not text.strip():
                flash(
                    "No text found. The PDF may be scanned "
                    "and may require OCR."
                )
                return redirect(url_for("index"))

            info = extract_information(text)

            with get_db() as conn:
                conn.execute("""
                    INSERT INTO candidates
                    (name, email, phone, education, skills, filename)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    info["name"],
                    info["email"],
                    info["phone"],
                    info["education"],
                    info["skills"],
                    safe_name
                ))

            flash("Resume processed successfully!")

        except Exception:
            app.logger.exception("Resume processing failed")
            flash("Could not process this resume. Check its format.")

        finally:
            # Do not retain the uploaded original by default.
            if os.path.exists(filepath):
                os.remove(filepath)

        return redirect(url_for("index"))

    query = request.args.get("q", "").strip()

    with get_db() as conn:
        if query:
            pattern = "%" + query + "%"
            candidates = conn.execute("""
                SELECT * FROM candidates
                WHERE name LIKE ?
                   OR email LIKE ?
                   OR education LIKE ?
                   OR skills LIKE ?
                ORDER BY id DESC
            """, (pattern, pattern, pattern, pattern)).fetchall()
        else:
            candidates = conn.execute("""
                SELECT * FROM candidates ORDER BY id DESC
            """).fetchall()

    return render_template(
        "index.html", candidates=candidates, query=query
    )


if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)
