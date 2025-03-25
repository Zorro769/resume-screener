from flask import Flask, render_template, request, jsonify, redirect, url_for
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import fitz
import docx
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import json
import re

app = Flask(__name__)

# Paths to JSON files
VACANCIES_JSON = "json_data/vacancies.json"
RESUMES_JSON = "json_data/resumes.json"

# Database configuration
engine = create_engine('sqlite:///jobs.db', echo=True)
Base = declarative_base()
Session = sessionmaker(bind=engine)

# Vacancy model
class Vacancy(Base):
    __tablename__ = 'vacancies'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    requirements = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# Resume model
class Resume(Base):
    __tablename__ = 'resumes'

    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    full_name = Column(String)
    email = Column(String)
    phone = Column(String)
    education = Column(Text)
    skills = Column(Text)
    experience = Column(Text)
    content = Column(Text)

# Create database tables
Base.metadata.create_all(engine)

def save_json(filepath, data):
    """Save data to a JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/create_vacancy', methods=['GET', 'POST'])
def create_vacancy():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        requirements = request.form.get('requirements')

        session = Session()
        vacancy = Vacancy(title=title, description=description, requirements=requirements)
        session.add(vacancy)
        session.commit()

        # Update JSON file with vacancies
        vacancies = session.query(Vacancy).all()
        save_json(VACANCIES_JSON, [
            {
                "id": v.id,
                "title": v.title,
                "description": v.description,
                "requirements": v.requirements,
                "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S")
            } for v in vacancies
        ])
        session.close()

        return redirect(url_for('vacancy_list'))
    return render_template('create_vacancy.html')

@app.route('/vacancies', methods=['GET'])
def vacancy_list():
    session = Session()
    vacancies = session.query(Vacancy).all()
    session.close()
    return render_template('vacancy_list.html', vacancies=vacancies)

# Return vacancies in JSON format
@app.route('/api/vacancies', methods=['GET'])
def get_vacancies_json():
    session = Session()
    vacancies = session.query(Vacancy).all()
    session.close()

    return jsonify([
        {
            "id": v.id,
            "title": v.title,
            "description": v.description,
            "requirements": v.requirements,
            "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S")
        } for v in vacancies
    ])

# Resume file upload and text extraction
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'pdf', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def extract_text(file_path):
    """Extract text from PDF or DOCX files."""
    text = ""
    if file_path.endswith(".pdf"):
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text("text") + "\n"
    elif file_path.endswith(".docx"):
        doc = docx.Document(file_path)
        text = "\n".join([p.text for p in doc.paragraphs])
    
    return text.strip()

def extract_resume_data(text):
    """Parse resume text and extract key details."""
    data = {}

    # Extract full name (assumes first line is name)
    lines = text.split("\n")
    data["full_name"] = lines[0].strip() if lines else "Not found"

    # Extract email
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    data["email"] = email_match.group(0) if email_match else "Not found"

    # Extract phone number
    phone_match = re.search(r"\+?\d[\d\s\-\(\)]{8,15}", text)
    data["phone"] = phone_match.group(0) if phone_match else "Not found"

    # Extract education
    education_match = re.findall(r"(university|college|degree|bachelor|master|phd|)", text, re.IGNORECASE)
    data["education"] = "Yes" if education_match else "Not found"

    # Extract skills
    skills_match = re.search(r"(Skills|):\s*(.+)", text, re.IGNORECASE)
    data["skills"] = skills_match.group(2) if skills_match else "Not found"

    # Extract experience
    experience_match = re.search(r"(Experience|):\s*(.+)", text, re.IGNORECASE)
    data["experience"] = experience_match.group(2) if experience_match else "Not found"

    return data

@app.route('/upload', methods=['POST'])
def upload_resume():
    if 'file' not in request.files:
        return "No file part", 400
    file = request.files['file']
    
    if file.filename == '':
        return "No selected file", 400
    
    if file and file.filename.split('.')[-1] in ALLOWED_EXTENSIONS:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Extract text and resume details
        resume_text = extract_text(filepath)
        resume_data = extract_resume_data(resume_text)

        session = Session()
        resume = Resume(
            filename=filename,
            full_name=resume_data["full_name"],
            email=resume_data["email"],
            phone=resume_data["phone"],
            education=resume_data["education"],
            skills=resume_data["skills"],
            experience=resume_data["experience"],
            content=resume_text
        )
        session.add(resume)
        session.commit()

        # Update JSON file with resumes
        resumes = session.query(Resume).all()
        save_json(RESUMES_JSON, [
            {
                "id": r.id,
                "filename": r.filename,
                "full_name": r.full_name,
                "email": r.email,
                "phone": r.phone,
                "education": r.education,
                "skills": r.skills,
                "experience": r.experience
            } for r in resumes
        ])
        session.close()

        return redirect(url_for('home'))

# Return resumes in JSON format
@app.route('/api/resumes', methods=['GET'])
def get_resumes_json():
    session = Session()
    resumes = session.query(Resume).all()
    session.close()

    return jsonify([
        {
            "id": r.id,
            "filename": r.filename,
            "full_name": r.full_name,
            "email": r.email,
            "phone": r.phone,
            "education": r.education,
            "skills": r.skills,
            "experience": r.experience
        } for r in resumes
    ])

if __name__ == '__main__':
    app.run(debug=True)
