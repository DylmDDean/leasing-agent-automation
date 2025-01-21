from flask import Flask, request, redirect, flash, render_template, send_file
from fpdf import FPDF
import os
import logging
import re
import io
import qrcode
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formatdate
from email import encoders
from google.cloud import vision
from dotenv import load_dotenv, find_dotenv
from endesive.pdf import cms
from datetime import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography import x509
import uuid

# Load environment variables
load_dotenv(find_dotenv(filename='my_env_variables.env'))

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'C:/New folder/htdocs/algo/scraping.json'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'C:/New folder/htdocs/algo/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}
app.secret_key = 'supersecretkey'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
logging.basicConfig(level=logging.INFO)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def unique_filename(filename):
    file_root, file_ext = os.path.splitext(filename)
    unique_name = f"{file_root}_{uuid.uuid4().hex}{file_ext}"
    return unique_name

@app.route('/')
def upload_form():
    return render_template('upload_form.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'paystub' not in request.files or 'id' not in request.files:
        logging.info('No file part in request')
        return render_template('error.html', error_message='No file part in request')

    paystub = request.files['paystub']
    id_file = request.files['id']
    recipient_email = request.form.get('email')
    signature = request.form.get('signature')
    sign_date = request.form.get('sign_date')

    logging.info(f"Paystub filename: {paystub.filename}")
    logging.info(f"ID filename: {id_file.filename}")
    logging.info(f"Email: {recipient_email}")
    logging.info(f"Signature: {signature}")
    logging.info(f"Date: {sign_date}")

    if paystub.filename == '' or id_file.filename == '' or not recipient_email or not signature or not sign_date:
        logging.info('No selected file, email, signature, or date')
        return render_template('error.html', error_message='No selected file, email, signature, or date')

    logging.info(f"Final Date: {sign_date}")  # Debugging

    if paystub and allowed_file(paystub.filename) and id_file and allowed_file(id_file.filename):
        paystub_filename = unique_filename(paystub.filename)
        id_filename = unique_filename(id_file.filename)

        paystub_path = os.path.join(app.config['UPLOAD_FOLDER'], paystub_filename)
        id_path = os.path.join(app.config['UPLOAD_FOLDER'], id_filename)
        
        paystub.save(paystub_path)
        id_file.save(id_path)

        logging.info(f'Paystub saved to {paystub_path}')
        logging.info(f'ID saved to {id_path}')
        
        paystub_results = process_image(paystub_path)
        id_results = process_image(id_path)
        
        logging.info(f'Paystub results: {paystub_results}')  
        logging.info(f'ID results: {id_results}')

        # Define the image path
        image_path = r"C:\New folder\htdocs\algo\wh.png"
        
        # Generate PDF with signature, date field, and image path
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'results.pdf')
        generate_pdf_with_signature_field(paystub_results, id_results, pdf_path, signature, sign_date, image_path)

        # Sign the PDF
        sign_pdf(pdf_path)

        # Send PDF via email
        send_email_with_attachment(recipient_email, 'Approval Results', 'Please find the attached approval results.', pdf_path)

        return render_template('approval_results.html', paystub_results=paystub_results, id_results=id_results)
    else:
        logging.info('File type not allowed')
        return render_template('error.html', error_message='File type not allowed')


def process_image(image_path):
    try:
        client = vision.ImageAnnotatorClient()
        
        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()

        image = vision.Image(content=content)

        response = client.document_text_detection(image=image)
        if response.error.message:
            raise Exception(response.error.message)

        texts = response.text_annotations
       
        text = texts[0].description if texts else ""
        logging.info(f'Extracted text: {text}')

        amount_pattern = r'Amount\s*\n?\s*\$\s*([\d,]+\.\d{2})'
        dln_pattern = r'DLN\s*(\w+)'

        results = []

        amount_match = re.search(amount_pattern, text, re.IGNORECASE)
        if amount_match:
            amount_value = float(amount_match.group(1).replace(',', ''))
            income_threshold = 4000
            decision = 'Approved' if amount_value >= income_threshold else 'Denied'
            logging.info(f'Amount Value: {amount_value}')
            results.append({'income': amount_value, 'decision': decision})
        else:
            logging.warning('No "Amount" value found in text.')
            results.append({'error': 'Integer not found'})

        dln_match = re.search(dln_pattern, text, re.IGNORECASE)
        if dln_match:
            dln_number = dln_match.group(1)
            logging.info(f'DLN: {dln_number}')
            results.append({'dln': dln_number, 'decision': 'Processed'})
        else:
            logging.warning('DLN not found.')
            results.append({'error': 'DLN not found'})

        return results

    except Exception as e:
        logging.error(f"Error processing image: {e}")
        return [{'error': 'Error processing image'}]

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph
from reportlab.lib.utils import ImageReader

def generate_pdf_with_signature_field(paystub_results, id_results, file_path, signature, sign_date, image_path):
    c = canvas.Canvas(file_path, pagesize=letter)
    width, height = letter

    # Center the header
    c.setFont("Helvetica-Bold", 16)
    header_text = "Approval Results"
    text_width = c.stringWidth(header_text, "Helvetica-Bold", 16)
    c.drawString((width - text_width) / 2.0, height - 40, header_text)

    y = height - 70
    c.setFont("Helvetica", 12)

    # Add Paystub Results
    for result in paystub_results:
        if 'error' not in result:
            c.drawString(100, y, f"Paystub Result: {result}")
            y -= 40  # Double the line spacing

    # Add ID Results
    for result in id_results:
        if 'error' not in result:
            c.drawString(100, y, f"ID Result: {result}")
            y -= 40  # Double the line spacing

    # Define left padding to align with Paystub and ID Results
    padding_left = 100
    padding_right = width - padding_left * 2

    # Add Legal Liability Section with the same alignment
    styles = getSampleStyleSheet()
    liability_text = ("LEGAL LIABILITY DISCLAIMER:\n"
                      "By signing below, you acknowledge that the information provided is accurate and true to the best of your knowledge. "
                      "You agree to release the provider from any liability or legal action arising from the use or misuse of this document.")

    liability_paragraph = Paragraph(liability_text, styles['Normal'])
    y -= 20  # Add some space before the disclaimer text
    liability_paragraph.wrapOn(c, padding_right, y)
    liability_paragraph.drawOn(c, padding_left, y)

    # Calculate the new y position after adding the liability text
    y -= (liability_paragraph.height + 10)  # Add some space before the signature and date

    # Add Signature and Date in regular font weight
    c.setFont("Helvetica", 12)
    c.drawString(padding_left, y, f"Signature: {signature}")
    y -= 20  # Double the line spacing
    c.drawString(padding_left, y, f"Date: {sign_date}")

    # Add the image below the date, aligned with the rest of the content
    y -= 10 # Add some space before the image
    image_width = 200
    image_height = 100
    image = ImageReader(image_path)
    c.drawImage(image, padding_left, y - image_height, width=image_width, height=image_height, mask='auto')

    c.save()

    print("PDF generated successfully with the signature field and image.")

import PyPDF2
from PyPDF2.generic import ByteStringObject, NameObject

def sign_pdf(file_path):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    from cryptography import x509

    private_key_path = "C:/Program Files (x86)/ASUS/ArmouryDevice/ssl/privatekey.key"
    certificate_path = "C:/Program Files (x86)/ASUS/ArmouryDevice/ssl/certificate.crt"

    # Load private key
    with open(private_key_path, 'rb') as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None,
            backend=default_backend()
        )

    # Load certificate
    with open(certificate_path, 'rb') as f:
        certificate = x509.load_pem_x509_certificate(f.read(), backend=default_backend())

    pdf_reader = PyPDF2.PdfReader(open(file_path, "rb"))
    pdf_writer = PyPDF2.PdfWriter()

    for page_num in range(len(pdf_reader.pages)):
        page = pdf_reader.pages[page_num]
        pdf_writer.add_page(page)

    # Add signature placeholder (this is a simplified example, for real signing more steps are needed)
    signature = ByteStringObject(private_key.sign(
        b"Sample Text to Sign",
        padding.PKCS1v15(),
        hashes.SHA256()
    ))
    pdf_writer._root_object.update({
        NameObject("/Contents"): signature
    })

    with open('signed_document.pdf', 'wb') as f:
        pdf_writer.write(f)

    logging.info(f'PDF signed and saved to signed_document.pdf')


def send_email_with_attachment(to_email, subject, body, file_path):
    from_email = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")

    print(f"From Email: {from_email}")
    print(f"Password: {password}")

    if from_email is None or password is None:
        logging.error("Email credentials not loaded")
        return

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject

    msg.attach(MIMEText(body))

    part = MIMEBase('application', 'octet-stream')
    part.set_payload(open(file_path, 'rb').read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename="results.pdf"')
    msg.attach(part)

    try:
        server = smtplib.SMTP('smtp.titan.email', 587)
        server.starttls()
        server.login(from_email, password)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        logging.info(f'Email sent to {to_email}')
    except Exception as e:
        logging.error(f'Failed to send email: {e}')

if __name__ == '__main__':
    app.run(debug=True)
        logging.error(f'Failed to send email: {e}')

if __name__ == '__main__':
    app.run(debug=True)
