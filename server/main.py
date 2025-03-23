from flask import Flask, render_template, request, redirect, url_for
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import fitz
import docx
from werkzeug.utils import secure_filename
from datetime import datetime
import os

app = Flask(__name__)

#sqlite engine
engine = create_engine('sqlite:///jobs.db', echo=True)
Base = declarative_base()
Session = sessionmaker(bind=engine)


#vacancy form for database
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

#making database 
Base.metadata.create_all(engine)

#main page
@app.route('/')
def home():
    return render_template('home.html')

#vacancy creation
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
        session.close()
        
        return redirect(url_for('vacancy_list'))
    return render_template('create_vacancy.html')

#vacancy list
@app.route('/vacancies')
def vacancy_list():
    session = Session()
    vacancies = session.query(Vacancy).all()
    session.close()
    return render_template('vacancy_list.html', vacancies=vacancies)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {".pdf", ".docx"}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

#file checker
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
#text from pdf
def extract_text_from_pdf(pdf_path):
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()
    return text
#text from word
def extract_text_from_docx(docx_path):
    doc = docx.Document(docx_path)
    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
    return text
#uploader
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

        #text extracteor
        extracted_text = ""
        if filename.endswith('.pdf'):
            extracted_text = extract_text_from_pdf(filepath)
        elif filename.endswith('.docx'):
            extracted_text = extract_text_from_docx(filepath)

        return f"File uploaded succesfully!<br><br><strong>EXtracted text</strong><br><pre>{extracted_text}</pre>"

    return "Not correct format of file", 400

if __name__ == '__main__':
    app.run(debug=True)