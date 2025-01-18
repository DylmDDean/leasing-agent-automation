from flask import Flask, request, redirect, flash, render_template
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
    
    if paystub.filename == '' or id_file.filename == '':
        logging.info('No selected file')
        return render_template('error.html', error_message='No selected file')

    if paystub and allowed_file(paystub.filename) and id_file and allowed_file(id_file.filename):
        paystub_filename = paystub.filename
        id_filename = id_file.filename

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

def generate_qr_code(data, file_path):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill='black', back_color='white')
    img.save(file_path)

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
    part.add_header('Content-Disposition', 'attachment; filename="qr_code.png"')
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
