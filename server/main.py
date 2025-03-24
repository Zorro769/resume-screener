from flask import Flask, render_template, request, redirect, url_for, jsonify
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import fitz
import docx
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import json

app = Flask(__name__)

# SQLite engine
engine = create_engine('sqlite:///jobs.db', echo=True)
Base = declarative_base()
Session = sessionmaker(bind=engine)

# Vacancy model for the database
class Vacancy(Base):
    __tablename__ = 'vacancies'
    
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    requirements = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __init__(self, title, description, requirements):
        self.title = title
        self.description = description
        self.requirements = requirements

# Create the database
Base.metadata.create_all(engine)

# Define folder for JSON data
JSON_FOLDER = "json_data"
if not os.path.exists(JSON_FOLDER):
    os.makedirs(JSON_FOLDER)
JSON_FILE = os.path.join(JSON_FOLDER, "vacancies.json")

# Main page
@app.route('/')
def home():
    return render_template('home.html')

# Vacancy creation
@app.route('/create_vacancy', methods=['GET', 'POST'])
def create_vacancy():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        requirements = request.form.get('requirements')
        
        session = Session()
        vacancy = Vacancy(
            title=title,
            description=description,
            requirements=requirements
        )
        
        session.add(vacancy)
        session.commit()
        
        data = {
            "id": vacancy.id,
            "title": vacancy.title,
            "description": vacancy.description,
            "requirements": vacancy.requirements,
            "created_at": vacancy.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "message": "Vacancy created!"
        }
        session.close()
        
        # Load existing JSON data from the file (if exists) or create empty list
        if os.path.exists(JSON_FILE):
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                try:
                    vacancies_data = json.load(f)
                except json.JSONDecodeError:
                    vacancies_data = []
        else:
            vacancies_data = []
        
        vacancies_data.append(data)
        
        # Save updated JSON data into the designated file
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(vacancies_data, f, indent=4, ensure_ascii=False)
        
        return jsonify(data), 201
    return '', 200

# Vacancy list
@app.route('/vacancies', methods=['GET'])
def vacancy_list():
    session = Session()
    vacancies = session.query(Vacancy).all()
    session.close()

    vacancies_json = [
        {
            "id": v.id,
            "title": v.title,
            "description": v.description,
            "requirements": v.requirements,
            "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S")
        } for v in vacancies
    ]

    return jsonify(vacancies_json)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "docx"} 
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# File checker
def allowed_file(filename):
    ext = filename.rsplit('.', 1)[1].lower()
    print(f"Debug tool for document: {ext}")
    return '.' in filename and ext in ALLOWED_EXTENSIONS

# Text extraction from PDF
def extract_text_from_pdf(pdf_path):
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()
    return text

# Text extraction from DOCX
def extract_text_from_docx(docx_path):
    doc = docx.Document(docx_path)
    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
    return text

# Uploader
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return "File is not found", 400

    file = request.files['file']

    if file.filename == '':
        return "File is not chosen", 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Text extractor
        extracted_text = ""
        if filepath.lower().endswith('.pdf'):
            extracted_text = extract_text_from_pdf(filepath)
        elif filepath.lower().endswith('.docx'):
            extracted_text = extract_text_from_docx(filepath)

        return f"File uploaded successfully!<br><br><strong>Extracted text:</strong><br><pre>{extracted_text}</pre>"

    return "Incorrect format of file", 400

if __name__ == '__main__':
    app.run(debug=True)
