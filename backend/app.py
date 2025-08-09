# backend/app.py

import os
import logging
from dotenv import load_dotenv
from datetime import timedelta
from urllib.parse import quote_plus
from flask import Flask, render_template, request, redirect, url_for, abort, flash, Response
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from io import BytesIO
from openpyxl import Workbook
from werkzeug.utils import secure_filename
import uuid

# Carregar variáveis de ambiente
load_dotenv()

# Versão
APP_VERSION = "Comemore+ v1.2.1"

# Logging
log_path = os.getenv("LOG_FILE", "logs/app.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_path), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config['APP_VERSION'] = APP_VERSION

# Uploads
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "mp4"}
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "static/uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.context_processor
def inject_version():
    return dict(app_version=app.config['APP_VERSION'])

# DB
db_url = f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
engine = create_engine(
    db_url,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
    pool_pre_ping=True,
    pool_timeout=10,
    connect_args={"connect_timeout": 5},
    future=True
)

# Login
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

class AdminUser(UserMixin):
    id = "admin"
    def check_password(self, password):
        return password == os.getenv("ADMIN_PASS")

@login_manager.user_loader
def load_user(user_id):
    if user_id == "admin":
        return AdminUser()
    return None

# Login
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == os.getenv("ADMIN_USER") and request.form["password"] == os.getenv("ADMIN_PASS"):
            login_user(AdminUser())
            logger.info("Login bem-sucedido.")
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("respostas"))
        flash("Usuário ou senha inválidos.", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("login"))

# Página convite
@app.route("/invite/<token>", methods=["GET","POST"])
def invite(token):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM invitees WHERE token=:token"), {"token": token}
        ).mappings().fetchone()
        if not result:
            abort(404)
        if request.method == "POST":
            response = request.form.get('response')
            observacao = request.form.get('observacao') or None
            if result['response'] is None and response in ['yes','no']:
                conn.execute(
                    text("""
                        UPDATE invitees
                        SET response=:response,
                            response_date=NOW(),
                            custom_message=:obs
                        WHERE token=:token
                    """),
                    {"response": response, "obs": observacao, "token": token}
                )
                conn.commit()
                logger.info(f"Resposta: {result['name']} -> {response} | Obs: {observacao}")
            return redirect(url_for('invite', token=token))

        settings = conn.execute(
            text("""SELECT `key`,`value` FROM settings
                    WHERE `key` IN ('question_text','yes_text','no_text','post_yes_text','post_no_text')""")
        ).mappings().all()
        texts = {r['key']: r['value'] for r in settings}

        return render_template("invite.html",
                               invitee=result,
                               question_text=texts.get('question_text'),
                               yes_text=texts.get('yes_text'),
                               no_text=texts.get('no_text'),
                               post_yes_text=texts.get('post_yes_text'),
                               post_no_text=texts.get('post_no_text'))

# Painel admin
@app.route("/admin/respostas")
@login_required
def respostas():
    page = int(request.args.get('page', 1))
    per_page = 20
    search = request.args.get('search', '').strip()
    offset = (page - 1) * per_page

    where_clause = ""
    params = {}
    if search:
        where_clause = " WHERE name LIKE :search OR email LIKE :search"
        params['search'] = f"%{search}%"

    order_clause = " ORDER BY response_date IS NULL, response_date DESC"

    sql = f"""SELECT id,name,email,phone,response,response_date,token,
                     custom_message,diaper_size,media_file
              FROM invitees {where_clause} {order_clause}
              LIMIT {per_page} OFFSET {offset}"""

    with engine.connect() as conn:
        result = conn.execute(text(sql), params).mappings().all()
        convidados = []
        for r in result:
            row = dict(r)
            if row['response_date']:
                row['response_date'] -= timedelta(hours=3)
            convidados.append(row)

        total_sql = f"SELECT COUNT(*) AS total FROM invitees {where_clause}"
        total_count = conn.execute(text(total_sql), {"search": params.get('search')}).mappings().fetchone()
        total_convidados = total_count['total']

        settings = conn.execute(
            text("""SELECT `key`,`value` FROM settings
                    WHERE `key` IN ('question_text','yes_text','no_text','post_yes_text','post_no_text')""")
        ).mappings().all()
        texts = {r['key']: r['value'] for r in settings}

        for row in convidados:
            if row['phone']:
                phone_clean = row['phone'].replace("(", "").replace(")", "").replace("-", "").replace(" ", "")
                invite_url = url_for('invite', token=row['token'], _external=True)
                message = f"{texts.get('question_text','')} {invite_url}"
                row['whatsapp_url'] = f"https://wa.me/55{phone_clean}?text={quote_plus(message, encoding='utf-8')}"
            else:
                row['whatsapp_url'] = None

    total_sim = sum(1 for c in convidados if c['response'] == 'yes')
    total_nao = sum(1 for c in convidados if c['response'] == 'no')
    total_aguardando = sum(1 for c in convidados if c['response'] is None)
    total_pages = (total_convidados + per_page - 1) // per_page

    return render_template(
        "admin_responses.html",
        convidados=convidados,
        texts=texts,
        total_sim=total_sim,
        total_nao=total_nao,
        total_aguardando=total_aguardando,
        page=page,
        total_pages=total_pages,
        search=search
    )

# Exportar Excel
@app.route("/admin/exportar_xlsx")
@login_required
def exportar_convidados_xlsx():
    search = request.args.get('search','').strip()
    where_clause = ""
    params = {}
    if search:
        where_clause = " WHERE name LIKE :search OR email LIKE :search"
        params['search'] = f"%{search}%"
    with engine.connect() as conn:
        sql = f"""SELECT name,email,phone,response,response_date,
                         custom_message,diaper_size,media_file
                  FROM invitees {where_clause}
                  ORDER BY response_date IS NULL, response_date DESC"""
        result = conn.execute(text(sql), params).mappings().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Convidados"
    ws.append(["Nome","Email","Telefone","Resposta","Data/Hora","Observação","Fralda","Arquivo"])
    for r in result:
        ws.append([
            r['name'],
            r['email'] or "",
            r['phone'] or "",
            r['response'] or "",
            r['response_date'].strftime("%d/%m/%Y %H:%M") if r['response_date'] else "",
            r['custom_message'] or "",
            r['diaper_size'] or "",
            r['media_file'] or ""
        ])
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max_len + 2

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return Response(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":"attachment;filename=convidados.xlsx"}
    )

# Adicionar convidado
@app.route("/admin/convidados/add", methods=['POST'])
@login_required
def add_convidado():
    name = request.form.get('name')
    email = request.form.get('email') or None
    phone = request.form.get('phone')
    msg = request.form.get('custom_message') or None
    diaper = request.form.get('diaper_size') or None

    media_filename = None
    file = request.files.get('media_file')
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Arquivo inválido. Use .jpg/.jpeg ou .mp4 (até 20MB).", "danger")
            return redirect(url_for('respostas'))
        ext = file.filename.rsplit(".", 1)[1].lower()
        safe = secure_filename(f"{uuid.uuid4().hex}.{ext}")
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], safe)
        file.save(save_path)
        media_filename = safe

    if not name:
        flash("Nome é obrigatório.","danger")
        return redirect(url_for('respostas'))

    token = os.urandom(16).hex()
    with engine.connect() as conn:
        conn.execute(
            text("""INSERT INTO invitees (name,email,phone,token,custom_message,diaper_size,media_file)
                    VALUES (:name,:email,:phone,:token,:msg,:diaper,:media)"""),
            {"name":name,"email":email,"phone":phone,"token":token,"msg":msg,"diaper":diaper,"media":media_filename}
        )
        conn.commit()

    flash(f"Convidado “{name}” adicionado com sucesso!","success")
    return redirect(url_for('respostas'))

@app.route("/admin/convidados/<int:id>/delete", methods=['POST'])
@login_required
def delete_convidado(id):
    with engine.connect() as conn:
        res = conn.execute(text("SELECT name, media_file FROM invitees WHERE id=:id"),{"id":id}).mappings().fetchone()
        conn.execute(text("DELETE FROM invitees WHERE id=:id"),{"id":id})
        conn.commit()
    # (Opcional) remover arquivo físico se desejar:
    # if res and res["media_file"]:
    #     try: os.remove(os.path.join(app.config["UPLOAD_FOLDER"], res["media_file"]))
    #     except FileNotFoundError: pass
    flash("Convidado excluído com sucesso.","warning")
    return redirect(url_for('respostas'))

@app.route("/admin/textos", methods=['POST'])
@login_required
def update_textos():
    textos = {
        "question_text":request.form.get('question_text') or "",
        "yes_text":request.form.get('yes_text') or "",
        "no_text":request.form.get('no_text') or "",
        "post_yes_text":request.form.get('post_yes_text') or "",
        "post_no_text":request.form.get('post_no_text') or ""
    }
    with engine.connect() as conn:
        for k,v in textos.items():
            conn.execute(text("REPLACE INTO settings (`key`,`value`) VALUES (:key,:value)"),{"key":k,"value":v})
        conn.commit()
    flash("Textos atualizados com sucesso!","success")
    return redirect(url_for('respostas'))

if __name__=="__main__":
    logger.info(f"Comemore+ iniciado. Versão: {APP_VERSION}")
    app.run(host="0.0.0.0",port=8000)
