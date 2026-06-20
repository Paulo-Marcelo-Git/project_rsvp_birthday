# backend/app.py

import os
import time
import logging
from functools import wraps
from dotenv import load_dotenv
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote_plus
from flask import Flask, render_template, request, redirect, url_for, abort, flash, Response
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from flask_wtf.csrf import CSRFProtect
from flasgger import Swagger
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from werkzeug.security import check_password_hash, generate_password_hash
from io import BytesIO
from openpyxl import Workbook
from werkzeug.utils import secure_filename
import uuid

load_dotenv()

with open(os.path.join(os.path.dirname(__file__), "..", "VERSION")) as _f:
    APP_VERSION = _f.read().strip()

log_path = os.getenv("LOG_FILE", "logs/app.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_path), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config['APP_VERSION'] = APP_VERSION
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

csrf = CSRFProtect(app)

swagger = Swagger(app, config={
    "headers": [],
    "specs": [{"endpoint": "apispec_1", "route": "/apispec_1.json",
               "rule_filter": lambda rule: True, "model_filter": lambda tag: True}],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
    "title": "Comemore+ API",
    "version": APP_VERSION,
    "description": "API do sistema de RSVP para convites de aniversário Comemore+.",
    "termsOfService": "",
    "contact": {"email": "seu@email.com"},
}, template={
    "info": {
        "title": "Comemore+ API",
        "description": "Documentação completa das APIs do sistema Comemore+.",
        "version": APP_VERSION,
    }
})

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "mp4", "png"}
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "static/uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
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

DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "102030@")

def _col_exists(conn, table, column):
    return conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = :t AND COLUMN_NAME = :c
    """), {"t": table, "c": column}).scalar()

def init_db():
    for attempt in range(10):
        try:
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS users (
                      id INT AUTO_INCREMENT PRIMARY KEY,
                      username VARCHAR(100) UNIQUE NOT NULL,
                      password_hash VARCHAR(255) NOT NULL,
                      must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                if not _col_exists(conn, 'invitees', 'user_id'):
                    conn.execute(text("""
                        ALTER TABLE invitees
                        ADD COLUMN user_id INT NULL,
                        ADD CONSTRAINT fk_invitees_user
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                    """))
                if not _col_exists(conn, 'users', 'must_change_password'):
                    conn.execute(text("""
                        ALTER TABLE users
                        ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT TRUE
                    """))

                # Migração: colunas email e whatsapp em users
                if not _col_exists(conn, 'users', 'email'):
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN email VARCHAR(255) NULL"
                    ))
                if not _col_exists(conn, 'users', 'whatsapp'):
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN whatsapp VARCHAR(30) NULL"
                    ))

                # Tabela de tokens de reset de senha
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS password_reset_tokens (
                      id         INT AUTO_INCREMENT PRIMARY KEY,
                      user_id    INT NOT NULL,
                      token      VARCHAR(64) NOT NULL UNIQUE,
                      expires_at DATETIME NOT NULL,
                      used       BOOLEAN NOT NULL DEFAULT FALSE,
                      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                      CONSTRAINT fk_prt_user
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                conn.commit()
            logger.info("DB inicializado com sucesso.")
            return
        except Exception as e:
            if attempt == 9:
                logger.error(f"Falha ao inicializar DB: {e}")
                raise
            logger.warning(f"DB não disponível, tentando novamente ({attempt+1}/10)...")
            time.sleep(2)

init_db()

# Auth
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

class AdminUser(UserMixin):
    id = "admin"
    is_super_admin = True
    db_id = None

    @property
    def username(self):
        return os.getenv("ADMIN_USER", "admin")

    def check_password(self, password):
        return check_password_hash(os.getenv("ADMIN_PASS"), password)

class DbUser(UserMixin):
    is_super_admin = False

    def __init__(self, db_id, username, password_hash, must_change_password=False):
        self.id = f"user_{db_id}"
        self.db_id = db_id
        self.username = username
        self._password_hash = password_hash
        self.must_change_password = bool(must_change_password)

    def check_password(self, password):
        return check_password_hash(self._password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    if user_id == "admin":
        return AdminUser()
    if user_id and user_id.startswith("user_"):
        try:
            db_id = int(user_id[5:])
        except ValueError:
            return None
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, username, password_hash, must_change_password FROM users WHERE id=:id"),
                {"id": db_id}
            ).mappings().fetchone()
            if row:
                return DbUser(row['id'], row['username'], row['password_hash'], row['must_change_password'])
    return None

def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated

@app.before_request
def protect_swagger():
    if (request.path.startswith('/apidocs') or request.path.startswith('/apispec')
            or request.path.startswith('/flasgger_static')):
        if not current_user.is_authenticated or not current_user.is_super_admin:
            return redirect(url_for('login'))


@app.before_request
def force_password_change():
    if (current_user.is_authenticated
            and not current_user.is_super_admin
            and getattr(current_user, 'must_change_password', False)
            and request.endpoint not in ('change_password', 'logout', 'static')):
        return redirect(url_for('change_password'))

# Helpers
def get_settings(conn):
    rows = conn.execute(
        text("""SELECT `key`,`value` FROM settings
                WHERE `key` IN ('question_text','yes_text','no_text','post_yes_text','post_no_text')""")
    ).mappings().all()
    return {r['key']: r['value'] for r in rows}

def save_uploaded_file(file):
    ext = file.filename.rsplit(".", 1)[1].lower()
    safe = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], safe)
    try:
        file.save(save_path)
    except OSError as e:
        logger.error(f"Falha ao salvar arquivo: {e}")
        return None
    return safe

def build_where(search, user_id=None, super_admin=False, alias=''):
    """Monta cláusula WHERE com filtro opcional por user_id e busca."""
    prefix = f"{alias}." if alias else ""
    conditions = []
    params = {}
    if not super_admin:
        conditions.append(f"{prefix}user_id = :user_id")
        params['user_id'] = user_id
    if search:
        conditions.append(f"({prefix}name LIKE :search OR {prefix}email LIKE :search)")
        params['search'] = f"%{search}%"
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params

def send_reset_email(to_address: str, username: str, reset_url: str) -> None:
    smtp_host = os.getenv('EMAIL_SMTP')
    smtp_user = os.getenv('EMAIL_USER')
    if not smtp_host or not smtp_user:
        logger.warning("EMAIL_SMTP/EMAIL_USER não configurados — email de reset não enviado.")
        return

    smtp_port = int(os.getenv('EMAIL_PORTA', '587'))
    smtp_pass = os.getenv('EMAIL_PASS', '')
    from_addr = f"Comemore+ <{smtp_user}>"
    subject   = "Redefinição de senha — Comemore+"

    html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;">
    <tr>
      <td align="center" style="padding:30px 10px;">
        <table width="520" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 20px rgba(0,0,0,0.08);max-width:520px;">
          <tr>
            <td style="background:linear-gradient(to right,#fce4ec,#e3f2fd);
                       padding:28px 40px;text-align:center;">
              <span style="font-size:28px;font-weight:700;color:#2c3e50;">
                &#127881; Comemore+
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 40px;">
              <p style="margin:0 0 16px;font-size:16px;color:#333;">
                Olá, <strong>{username}</strong>!
              </p>
              <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6;">
                Recebemos uma solicitação para redefinir a senha da sua conta
                no <strong>Comemore+</strong>.
              </p>
              <table cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center" style="padding:8px 0 28px;">
                    <a href="{reset_url}"
                       style="display:inline-block;background:#1976d2;color:#ffffff;
                              text-decoration:none;font-size:15px;font-weight:600;
                              border-radius:8px;padding:14px 32px;">
                      Redefinir minha senha
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 8px;font-size:13px;color:#888;">
                Este link é válido por <strong>1 hora</strong>.
              </p>
              <p style="margin:0 0 24px;font-size:13px;color:#888;">
                Se você não solicitou a redefinição, ignore este email
                — sua senha permanece a mesma.
              </p>
              <hr style="border:none;border-top:1px solid #eee;margin:0 0 20px;">
              <p style="margin:0;font-size:12px;color:#aaa;">
                Caso o botão não funcione, copie e cole o link abaixo no seu navegador:<br>
                <span style="color:#1976d2;word-break:break-all;">{reset_url}</span>
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#f5f5f5;padding:20px 40px;text-align:center;
                       border-top:1px solid #eee;">
              <p style="margin:0;font-size:12px;color:#888;">
                &copy; 2025 Comemore+ &middot; {smtp_user}<br>
                Este é um email automático, não responda.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    text_body = (
        f"Olá, {username}!\n\n"
        f"Você solicitou a redefinição de senha da sua conta no Comemore+.\n\n"
        f"Acesse o link abaixo para criar uma nova senha (válido por 1 hora):\n"
        f"{reset_url}\n\n"
        f"Se você não solicitou isso, ignore este email.\n\n"
        f"-- Equipe Comemore+"
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = from_addr
    msg['To']      = to_address
    msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html',  'utf-8'))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, to_address, msg.as_string())
            logger.info(f"Email de reset enviado para '{to_address}'.")
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Falha ao enviar email de reset para '{to_address}': {e}")

# Rotas
@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Login de usuário
    ---
    tags: [Auth]
    parameters:
      - in: formData
        name: username
        type: string
        required: true
      - in: formData
        name: password
        type: string
        required: true
    responses:
      302:
        description: Redireciona para /admin/respostas (sucesso) ou reexibe form (falha)
      200:
        description: Página de login
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = None

        if username == os.getenv("ADMIN_USER"):
            candidate = AdminUser()
            if candidate.check_password(password):
                user = candidate
        else:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT id, username, password_hash, must_change_password FROM users WHERE username=:u"),
                    {"u": username}
                ).mappings().fetchone()
                if row:
                    candidate = DbUser(row['id'], row['username'], row['password_hash'], row['must_change_password'])
                    if candidate.check_password(password):
                        user = candidate

        if user:
            login_user(user)
            logger.info(f"Login bem-sucedido: '{username}'.")
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("respostas"))

        logger.warning(f"Tentativa de login inválida: '{username}'.")
        flash("Usuário ou senha inválidos.", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    """
    Encerra a sessão do usuário
    ---
    tags: [Auth]
    responses:
      302:
        description: Redireciona para /login
    """
    logout_user()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("login"))


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    """
    Solicitar redefinição de senha por email
    ---
    tags: [Auth]
    parameters:
      - in: formData
        name: username
        type: string
        required: true
    responses:
      302:
        description: Sempre redireciona para /login com mensagem genérica
      200:
        description: Formulário de solicitação
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email_to_send = None
        username_to_send = None
        token_to_send = None

        with engine.connect() as conn:
            row = conn.execute(
                text("""SELECT id, username, email
                        FROM users WHERE username=:u"""),
                {"u": username}
            ).mappings().fetchone()

            if row and row['email']:
                token = uuid.uuid4().hex
                expires = datetime.utcnow() + timedelta(hours=1)
                conn.execute(
                    text("""INSERT INTO password_reset_tokens
                            (user_id, token, expires_at) VALUES (:uid, :tok, :exp)"""),
                    {"uid": row['id'], "tok": token, "exp": expires}
                )
                conn.commit()
                base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
                email_to_send = row['email']
                username_to_send = row['username']
                token_to_send = f"{base_url}/reset_password/{token}"

        if email_to_send:
            try:
                send_reset_email(email_to_send, username_to_send, token_to_send)
            except Exception as e:
                logger.error(f"Erro ao enviar email de reset: {e}")

        flash("Se o usuário existir e tiver email cadastrado, "
              "você receberá um link de redefinição em breve.", "info")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


def _get_valid_token(conn, token: str):
    """Retorna a row do token se válido (existente, não usado, não expirado)."""
    return conn.execute(
        text("""SELECT id, user_id FROM password_reset_tokens
                WHERE token=:tok AND used=FALSE AND expires_at > UTC_TIMESTAMP()"""),
        {"tok": token}
    ).mappings().fetchone()


@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """
    Redefinir senha via token de email
    ---
    tags: [Auth]
    parameters:
      - in: path
        name: token
        type: string
        required: true
      - in: formData
        name: new_password
        type: string
        required: false
      - in: formData
        name: confirm_password
        type: string
        required: false
    responses:
      302:
        description: Sucesso redireciona /login; token inválido redireciona /forgot_password
      200:
        description: Formulário de nova senha
    """
    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm      = request.form.get("confirm_password", "")

        if len(new_password) < 8:
            flash("A senha deve ter pelo menos 8 caracteres.", "danger")
            return render_template("reset_password.html", token=token)
        if new_password == DEFAULT_PASSWORD:
            flash("Escolha uma senha diferente da senha padrão.", "danger")
            return render_template("reset_password.html", token=token)
        if new_password != confirm:
            flash("As senhas não coincidem.", "danger")
            return render_template("reset_password.html", token=token)

        with engine.connect() as conn:
            tok_row = _get_valid_token(conn, token)
            if not tok_row:
                flash("Link de redefinição inválido ou expirado.", "danger")
                return redirect(url_for("forgot_password"))
            conn.execute(
                text("UPDATE users SET password_hash=:pw, must_change_password=FALSE WHERE id=:id"),
                {"pw": generate_password_hash(new_password), "id": tok_row['user_id']}
            )
            conn.execute(
                text("UPDATE password_reset_tokens SET used=TRUE WHERE id=:id"),
                {"id": tok_row['id']}
            )
            conn.commit()

        logger.info(f"Senha redefinida via token para user_id={tok_row['user_id']}.")
        flash("Senha redefinida com sucesso! Faça login com sua nova senha.", "success")
        return redirect(url_for("login"))

    with engine.connect() as conn:
        tok_row = _get_valid_token(conn, token)
        if not tok_row:
            flash("Link de redefinição inválido ou expirado.", "danger")
            return redirect(url_for("forgot_password"))
    return render_template("reset_password.html", token=token)


@app.route("/invite/<token>", methods=["GET", "POST"])
@csrf.exempt
def invite(token):
    """
    Página de confirmação de presença do convidado
    ---
    tags: [Convite]
    parameters:
      - in: path
        name: token
        type: string
        required: true
      - in: formData
        name: response
        type: string
        enum: [yes, no]
        required: false
      - in: formData
        name: observacao
        type: string
        required: false
    responses:
      200:
        description: Página de convite
      404:
        description: Token inválido
    """
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM invitees WHERE token=:token"), {"token": token}
        ).mappings().fetchone()
        if not result:
            abort(404)
        if request.method == "POST":
            response = request.form.get('response')
            observacao = request.form.get('observacao') or None
            if result['response'] is None and response in ['yes', 'no']:
                conn.execute(
                    text("""UPDATE invitees
                            SET response=:response, response_date=NOW(), custom_message=:obs
                            WHERE token=:token"""),
                    {"response": response, "obs": observacao, "token": token}
                )
                conn.commit()
                logger.info(f"Resposta: {result['name']} -> {response} | Obs: {observacao}")
            return redirect(url_for('invite', token=token))

        texts = get_settings(conn)
        return render_template("invite.html",
                               invitee=result,
                               question_text=texts.get('question_text'),
                               yes_text=texts.get('yes_text'),
                               no_text=texts.get('no_text'),
                               post_yes_text=texts.get('post_yes_text'),
                               post_no_text=texts.get('post_no_text'))

@app.route("/admin/respostas")
@login_required
def respostas():
    """
    Lista de respostas dos convidados
    ---
    tags: [Respostas]
    parameters:
      - in: query
        name: page
        type: integer
        default: 1
      - in: query
        name: search
        type: string
    responses:
      200:
        description: Lista paginada de respostas
      302:
        description: Redireciona para /login se não autenticado
    """
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 50
    search = request.args.get('search', '').strip()
    offset = (page - 1) * per_page

    is_admin = current_user.is_super_admin
    uid = None if is_admin else current_user.db_id
    where_clause, params = build_where(search, user_id=uid, super_admin=is_admin, alias='i')
    order_clause = " ORDER BY i.response_date IS NULL, i.response_date DESC"
    params['limit'] = per_page
    params['offset'] = offset
    count_params = {k: v for k, v in params.items() if k not in ('limit', 'offset')}

    with engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT i.id, i.name, i.email, i.phone, i.response, i.response_date,
                   i.token, i.custom_message, i.media_file,
                   COALESCE(u.username, '(admin)') AS owner_username
            FROM invitees i
            LEFT JOIN users u ON i.user_id = u.id
            {where_clause} {order_clause}
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

        tz_offset = int(os.getenv("TZ_OFFSET_HOURS", "-3"))
        convidados = []
        for r in result:
            row = dict(r)
            if row['response_date']:
                row['response_date'] += timedelta(hours=tz_offset)
            convidados.append(row)

        total_count = conn.execute(text(f"""
            SELECT COUNT(*) AS total
            FROM invitees i LEFT JOIN users u ON i.user_id = u.id
            {where_clause}
        """), count_params).mappings().fetchone()
        total_convidados = total_count['total']

        counts = conn.execute(text(f"""
            SELECT
              SUM(CASE WHEN i.response = 'yes' THEN 1 ELSE 0 END) AS total_sim,
              SUM(CASE WHEN i.response = 'no'  THEN 1 ELSE 0 END) AS total_nao,
              SUM(CASE WHEN i.response IS NULL  THEN 1 ELSE 0 END) AS total_aguardando
            FROM invitees i LEFT JOIN users u ON i.user_id = u.id
            {where_clause}
        """), count_params).mappings().fetchone()
        total_sim = counts['total_sim'] or 0
        total_nao = counts['total_nao'] or 0
        total_aguardando = counts['total_aguardando'] or 0

        texts = get_settings(conn)

        for row in convidados:
            if row['phone']:
                phone_clean = row['phone'].replace("(","").replace(")","").replace("-","").replace(" ","")
                invite_url = url_for('invite', token=row['token'], _external=True)
                message = f"{texts.get('question_text', '')} {invite_url}"
                row['whatsapp_url'] = f"https://wa.me/55{phone_clean}?text={quote_plus(message, encoding='utf-8')}"
            else:
                row['whatsapp_url'] = None

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
        search=search,
        is_super_admin=is_admin
    )

@app.route("/admin/exportar_xlsx")
@login_required
def exportar_convidados_xlsx():
    """
    Download da lista de convidados em Excel
    ---
    tags: [Respostas]
    responses:
      200:
        description: Arquivo .xlsx para download
      302:
        description: Redireciona para /login se não autenticado
    """
    search = request.args.get('search', '').strip()
    is_admin = current_user.is_super_admin
    uid = None if is_admin else current_user.db_id
    where_clause, params = build_where(search, user_id=uid, super_admin=is_admin)

    with engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT name, email, phone, response, response_date, custom_message, media_file
            FROM invitees
            {where_clause}
            ORDER BY response_date IS NULL, response_date DESC
        """), params).mappings().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Convidados"
    ws.append(["Nome", "Email", "Telefone", "Resposta", "Data/Hora", "Observação", "Arquivo"])
    for r in result:
        ws.append([
            r['name'], r['email'] or "", r['phone'] or "",
            r['response'] or "",
            r['response_date'].strftime("%d/%m/%Y %H:%M") if r['response_date'] else "",
            r['custom_message'] or "", r['media_file'] or ""
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
        headers={"Content-Disposition": "attachment;filename=convidados.xlsx"}
    )

@app.route("/admin/convidados/add", methods=['POST'])
@login_required
def add_convidado():
    """
    Adicionar novo convidado
    ---
    tags: [Convidados]
    parameters:
      - in: formData
        name: name
        type: string
        required: true
      - in: formData
        name: email
        type: string
      - in: formData
        name: phone
        type: string
      - in: formData
        name: media_file
        type: file
    responses:
      302:
        description: Redireciona para /admin/respostas
      403:
        description: Sem permissão
    """
    name = request.form.get('name', '').strip()
    if not name:
        flash("Nome é obrigatório.", "danger")
        return redirect(url_for('respostas'))

    email = request.form.get('email') or None
    phone = request.form.get('phone') or None
    msg = request.form.get('custom_message') or None
    user_id = None if current_user.is_super_admin else current_user.db_id

    media_filename = None
    file = request.files.get('media_file')
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Arquivo inválido. Use .jpg/.jpeg/.png ou .mp4 (até 20MB).", "danger")
            return redirect(url_for('respostas'))
        media_filename = save_uploaded_file(file)
        if media_filename is None:
            flash("Erro ao salvar arquivo. Tente novamente.", "danger")
            return redirect(url_for('respostas'))

    token = os.urandom(16).hex()
    with engine.connect() as conn:
        conn.execute(
            text("""INSERT INTO invitees (name,email,phone,token,custom_message,media_file,user_id)
                    VALUES (:name,:email,:phone,:token,:msg,:media,:user_id)"""),
            {"name": name, "email": email, "phone": phone, "token": token,
             "msg": msg, "media": media_filename, "user_id": user_id}
        )
        conn.commit()

    logger.info(f"Convidado adicionado: '{name}' por '{current_user.username}'.")
    flash(f'Convidado "{name}" adicionado com sucesso!', "success")
    return redirect(url_for('respostas'))

@app.route("/admin/convidados/<int:id>/edit", methods=['POST'])
@login_required
def edit_convidado(id):
    """
    Editar dados de convidado
    ---
    tags: [Convidados]
    parameters:
      - in: path
        name: id
        type: integer
        required: true
      - in: formData
        name: name
        type: string
      - in: formData
        name: email
        type: string
      - in: formData
        name: phone
        type: string
    responses:
      302:
        description: Redireciona para /admin/respostas
      403:
        description: Sem permissão
      404:
        description: Convidado não encontrado
    """
    with engine.connect() as conn:
        guest = conn.execute(
            text("SELECT user_id FROM invitees WHERE id=:id"), {"id": id}
        ).mappings().fetchone()

    if not guest:
        abort(404)
    if not current_user.is_super_admin and guest['user_id'] != current_user.db_id:
        abort(403)

    name = request.form.get('name', '').strip()
    email = request.form.get('email') or None
    phone = request.form.get('phone') or None
    msg = request.form.get('custom_message') or None
    response_val = request.form.get('response')
    if response_val not in ('yes', 'no', ''):
        response_val = ''
    response_db = None if response_val == '' else response_val

    new_media = None
    file = request.files.get('media_file')
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Arquivo inválido. Use .jpg/.jpeg/.png ou .mp4 (até 20MB).", "danger")
            return redirect(url_for('respostas'))
        new_media = save_uploaded_file(file)
        if new_media is None:
            flash("Erro ao salvar arquivo. Tente novamente.", "danger")
            return redirect(url_for('respostas'))

    with engine.connect() as conn:
        media_part = ", media_file=:media_file" if new_media else ""
        conn.execute(
            text(f"""UPDATE invitees
                     SET name=:name, email=:email, phone=:phone,
                         custom_message=:msg, response=:response
                         {media_part}
                     WHERE id=:id"""),
            {"name": name, "email": email, "phone": phone, "msg": msg,
             "response": response_db, "media_file": new_media, "id": id}
        )
        conn.commit()

    logger.info(f"Convidado id={id} atualizado por '{current_user.username}'.")
    flash("Convidado atualizado com sucesso!", "success")
    return redirect(url_for('respostas'))

@app.route("/admin/convidados/<int:id>/delete", methods=['POST'])
@login_required
def delete_convidado(id):
    """
    Excluir convidado
    ---
    tags: [Convidados]
    parameters:
      - in: path
        name: id
        type: integer
        required: true
    responses:
      302:
        description: Redireciona para /admin/respostas
      403:
        description: Sem permissão
      404:
        description: Convidado não encontrado
    """
    with engine.connect() as conn:
        res = conn.execute(
            text("SELECT name, media_file, user_id FROM invitees WHERE id=:id"), {"id": id}
        ).mappings().fetchone()

    if not res:
        abort(404)
    if not current_user.is_super_admin and res['user_id'] != current_user.db_id:
        abort(403)

    with engine.connect() as conn:
        conn.execute(text("DELETE FROM invitees WHERE id=:id"), {"id": id})
        conn.commit()

    if res["media_file"]:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], res["media_file"]))
        except FileNotFoundError:
            pass

    logger.info(f"Convidado '{res['name']}' (id={id}) excluído por '{current_user.username}'.")
    flash("Convidado excluído com sucesso.", "warning")
    return redirect(url_for('respostas'))

@app.route("/admin/textos", methods=['POST'])
@login_required
@super_admin_required
def update_textos():
    """
    Atualizar textos do convite
    ---
    tags: [Textos]
    parameters:
      - in: formData
        name: question_text
        type: string
      - in: formData
        name: yes_text
        type: string
      - in: formData
        name: no_text
        type: string
      - in: formData
        name: post_yes_text
        type: string
      - in: formData
        name: post_no_text
        type: string
    responses:
      302:
        description: Redireciona para /admin/respostas
      403:
        description: Apenas super admin
    """
    textos = {
        "question_text": request.form.get('question_text') or "",
        "yes_text":      request.form.get('yes_text') or "",
        "no_text":       request.form.get('no_text') or "",
        "post_yes_text": request.form.get('post_yes_text') or "",
        "post_no_text":  request.form.get('post_no_text') or ""
    }
    with engine.connect() as conn:
        for k, v in textos.items():
            conn.execute(
                text("REPLACE INTO settings (`key`,`value`) VALUES (:key,:value)"),
                {"key": k, "value": v}
            )
        conn.commit()
    logger.info(f"Textos do convite atualizados por '{current_user.username}'.")
    flash("Textos atualizados com sucesso!", "success")
    return redirect(url_for('respostas'))

# ===== Gerenciamento de Usuários =====

@app.route("/admin/usuarios")
@login_required
@super_admin_required
def admin_usuarios():
    """
    Listar todos os sub-usuários
    ---
    tags: [Usuários]
    responses:
      200:
        description: Página de gerenciamento de usuários
      403:
        description: Apenas super admin
    """
    with engine.connect() as conn:
        users = conn.execute(
            text("SELECT id, username, email, whatsapp, must_change_password, created_at FROM users ORDER BY created_at DESC")
        ).mappings().all()
        counts_rows = conn.execute(
            text("""SELECT user_id, COUNT(*) AS total FROM invitees
                    WHERE user_id IS NOT NULL GROUP BY user_id""")
        ).mappings().all()

    counts_map = {r['user_id']: r['total'] for r in counts_rows}
    users_list = [dict(u) | {"guest_count": counts_map.get(u['id'], 0)} for u in users]
    return render_template("admin_users.html", users=users_list, default_password=DEFAULT_PASSWORD)

@app.route("/admin/usuarios/add", methods=['POST'])
@login_required
@super_admin_required
def add_usuario():
    """
    Criar novo sub-usuário
    ---
    tags: [Usuários]
    parameters:
      - in: formData
        name: username
        type: string
        required: true
      - in: formData
        name: email
        type: string
        required: true
      - in: formData
        name: whatsapp
        type: string
    responses:
      302:
        description: Redireciona para /admin/usuarios
      403:
        description: Apenas super admin
    """
    username = request.form.get('username', '').strip()
    email    = request.form.get('email', '').strip()
    whatsapp = request.form.get('whatsapp', '').strip() or None

    if not username:
        flash("Nome de usuário é obrigatório.", "danger")
        return redirect(url_for('admin_usuarios'))
    if not email:
        flash("Email é obrigatório.", "danger")
        return redirect(url_for('admin_usuarios'))

    try:
        with engine.connect() as conn:
            conn.execute(
                text("""INSERT INTO users (username, password_hash, must_change_password, email, whatsapp)
                        VALUES (:u, :pw, TRUE, :email, :whatsapp)"""),
                {"u": username, "pw": generate_password_hash(DEFAULT_PASSWORD),
                 "email": email, "whatsapp": whatsapp}
            )
            conn.commit()
        logger.info(f"Usuário '{username}' criado por '{current_user.username}'.")
        flash(f'Usuário "{username}" criado. Senha padrão: {DEFAULT_PASSWORD}', "success")
    except Exception:
        flash("Erro: nome de usuário ou email já existe.", "danger")

    return redirect(url_for('admin_usuarios'))

@app.route("/admin/usuarios/<int:id>/edit", methods=['POST'])
@login_required
@super_admin_required
def edit_usuario(id):
    """
    Editar sub-usuário
    ---
    tags: [Usuários]
    parameters:
      - in: path
        name: id
        type: integer
        required: true
      - in: formData
        name: username
        type: string
        required: true
      - in: formData
        name: email
        type: string
        required: true
      - in: formData
        name: whatsapp
        type: string
    responses:
      302:
        description: Redireciona para /admin/usuarios
      403:
        description: Apenas super admin
      404:
        description: Usuário não encontrado
    """
    new_username = request.form.get('username', '').strip()
    new_email    = request.form.get('email', '').strip()
    new_whatsapp = request.form.get('whatsapp', '').strip() or None

    if not new_username:
        flash("Nome de usuário não pode ser vazio.", "danger")
        return redirect(url_for('admin_usuarios'))
    if not new_email:
        flash("Email é obrigatório.", "danger")
        return redirect(url_for('admin_usuarios'))

    try:
        with engine.connect() as conn:
            user = conn.execute(
                text("SELECT username FROM users WHERE id=:id"), {"id": id}
            ).mappings().fetchone()
            if not user:
                abort(404)
            conn.execute(
                text("UPDATE users SET username=:u, email=:email, whatsapp=:whatsapp WHERE id=:id"),
                {"u": new_username, "email": new_email, "whatsapp": new_whatsapp, "id": id}
            )
            conn.commit()
        logger.info(f"Usuário id={id} atualizado por '{current_user.username}'.")
        flash(f'Usuário "{new_username}" atualizado.', "success")
    except Exception:
        flash("Erro: nome de usuário ou email já existe.", "danger")

    return redirect(url_for('admin_usuarios'))

@app.route("/admin/usuarios/<int:id>/reset_senha", methods=['POST'])
@login_required
@super_admin_required
def reset_senha_usuario(id):
    """
    Resetar senha de sub-usuário para a senha padrão (admin)
    ---
    tags: [Usuários]
    parameters:
      - in: path
        name: id
        type: integer
        required: true
    responses:
      302:
        description: Redireciona para /admin/usuarios
      403:
        description: Apenas super admin
      404:
        description: Usuário não encontrado
    """
    with engine.connect() as conn:
        user = conn.execute(
            text("SELECT username FROM users WHERE id=:id"), {"id": id}
        ).mappings().fetchone()
        if not user:
            abort(404)
        conn.execute(
            text("UPDATE users SET password_hash=:pw, must_change_password=TRUE WHERE id=:id"),
            {"pw": generate_password_hash(DEFAULT_PASSWORD), "id": id}
        )
        conn.commit()
    logger.info(f"Senha de '{user['username']}' (id={id}) resetada por '{current_user.username}'.")
    flash(f'Senha de "{user["username"]}" resetada para a senha padrão.', "success")
    return redirect(url_for('admin_usuarios'))

@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    """
    Troca de senha obrigatória para sub-usuários
    ---
    tags: [Auth]
    parameters:
      - in: formData
        name: new_password
        type: string
        required: true
      - in: formData
        name: confirm_password
        type: string
        required: true
    responses:
      302:
        description: Redireciona para /admin/respostas após sucesso
      200:
        description: Formulário de troca de senha
    """
    if current_user.is_super_admin:
        return redirect(url_for('respostas'))

    if request.method == "POST":
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        if new_password == DEFAULT_PASSWORD:
            flash("Escolha uma senha diferente da senha padrão.", "danger")
            return render_template("change_password.html")
        if len(new_password) < 8:
            flash("A senha deve ter pelo menos 8 caracteres.", "danger")
            return render_template("change_password.html")
        if new_password != confirm:
            flash("As senhas não coincidem.", "danger")
            return render_template("change_password.html")

        with engine.connect() as conn:
            conn.execute(
                text("UPDATE users SET password_hash=:pw, must_change_password=FALSE WHERE id=:id"),
                {"pw": generate_password_hash(new_password), "id": current_user.db_id}
            )
            conn.commit()

        login_user(load_user(current_user.id))
        logger.info(f"Usuário '{current_user.username}' alterou sua senha.")
        flash("Senha alterada com sucesso!", "success")
        return redirect(url_for('respostas'))

    return render_template("change_password.html")

@app.route("/admin/usuarios/<int:id>/delete", methods=['POST'])
@login_required
@super_admin_required
def delete_usuario(id):
    """
    Excluir sub-usuário
    ---
    tags: [Usuários]
    parameters:
      - in: path
        name: id
        type: integer
        required: true
    responses:
      302:
        description: Redireciona para /admin/usuarios
      403:
        description: Apenas super admin
      404:
        description: Usuário não encontrado
    """
    with engine.connect() as conn:
        user = conn.execute(
            text("SELECT username FROM users WHERE id=:id"), {"id": id}
        ).mappings().fetchone()
        if not user:
            abort(404)
        conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": id})
        conn.commit()

    logger.info(f"Usuário '{user['username']}' (id={id}) excluído por '{current_user.username}'.")
    flash(f'Usuário "{user["username"]}" excluído. Seus convidados ficaram sem dono (visíveis só ao admin).', "warning")
    return redirect(url_for('admin_usuarios'))

if __name__ == "__main__":
    logger.info(f"Comemore+ iniciado. Versão: {APP_VERSION}")
    app.run(host="0.0.0.0", port=8000)
