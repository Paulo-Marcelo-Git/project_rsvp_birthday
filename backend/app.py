# backend/app.py

import logging
import os
import secrets
import smtplib
import time
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from io import BytesIO
from urllib.parse import quote_plus

from dotenv import load_dotenv
from flasgger import Swagger
from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf.csrf import CSRFProtect
from openpyxl import Workbook
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import repo

load_dotenv()

with open(os.path.join(os.path.dirname(__file__), "..", "VERSION")) as _f:
    APP_VERSION = _f.read().strip()

log_path = os.getenv("LOG_FILE", "logs/app.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config["APP_VERSION"] = APP_VERSION
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["SESSION_REFRESH_EACH_REQUEST"] = True

csrf = CSRFProtect(app)

swagger = Swagger(
    app,
    config={
        "headers": [],
        "specs": [
            {
                "endpoint": "apispec_1",
                "route": "/apispec_1.json",
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/apidocs/",
        "title": "Comemore+ API",
        "version": APP_VERSION,
        "description": "API do sistema de RSVP para convites de aniversário Comemore+.",
        "termsOfService": "",
        "contact": {"email": os.getenv("EMAIL_USER", "")},
    },
    template={
        "info": {
            "title": "Comemore+ API",
            "description": "Documentação completa das APIs do sistema Comemore+.",
            "version": APP_VERSION,
        }
    },
)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "mp4", "png"}
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "static/uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.context_processor
def inject_version():
    return dict(app_version=app.config["APP_VERSION"])


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
    future=True,
)

DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "102030@")

# Auth
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


class AdminUser(UserMixin):
    id = "admin"
    is_super_admin = True
    db_id = None
    tenant_id = 1       # default tenant até signup substituir env-var auth (2D)
    role = "tenant_admin"

    @property
    def username(self):
        return os.getenv("ADMIN_USER", "admin")

    def check_password(self, password):
        return check_password_hash(os.getenv("ADMIN_PASS"), password)


class DbUser(UserMixin):
    def __init__(
        self,
        db_id,
        username,
        password_hash,
        must_change_password=False,
        tenant_id=1,
        role="member",
    ):
        self.id = f"user_{db_id}"
        self.db_id = db_id
        self.username = username
        self._password_hash = password_hash
        self.must_change_password = bool(must_change_password)
        self.tenant_id = tenant_id
        self.role = role

    @property
    def is_super_admin(self):
        return self.role == "tenant_admin"

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
            row = (
                conn.execute(
                    text(
                        "SELECT id, tenant_id, username, password_hash, "
                        "must_change_password, role "
                        "FROM users WHERE id=:id AND is_active=1"
                    ),
                    {"id": db_id},
                )
                .mappings()
                .fetchone()
            )
            if row:
                return DbUser(
                    row["id"],
                    row["username"],
                    row["password_hash"],
                    row["must_change_password"],
                    row["tenant_id"],
                    row["role"],
                )
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
    if (
        request.path.startswith("/apidocs")
        or request.path.startswith("/apispec")
        or request.path.startswith("/flasgger_static")
    ):
        if not current_user.is_authenticated or not current_user.is_super_admin:
            return redirect(url_for("login"))


@app.before_request
def force_password_change():
    if (
        current_user.is_authenticated
        and not current_user.is_super_admin
        and getattr(current_user, "must_change_password", False)
        and request.endpoint not in ("change_password", "logout", "static")
    ):
        return redirect(url_for("change_password"))


# Helpers
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


def send_reset_email(to_address: str, username: str, reset_url: str) -> None:
    smtp_host = os.getenv("EMAIL_SMTP")
    smtp_user = os.getenv("EMAIL_USER")
    if not smtp_host or not smtp_user:
        logger.warning(
            "EMAIL_SMTP/EMAIL_USER não configurados — email de reset não enviado."
        )
        return

    smtp_port = int(os.getenv("EMAIL_PORTA", "587"))
    smtp_pass = os.getenv("EMAIL_PASS", "")
    from_addr = f"Comemore+ <{smtp_user}>"
    subject = "Redefinição de senha — Comemore+"

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
                &copy; 2026 Comemore+ &middot; {smtp_user}<br>
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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

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
        name: email
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
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = None

        # TRANSITÓRIO (2D): bloco ADMIN_EMAIL sai quando signup criar DbUser tenant_admin
        admin_email = os.getenv("ADMIN_EMAIL", "").lower()
        if admin_email and email == admin_email:
            candidate = AdminUser()
            if candidate.check_password(password):
                user = candidate
        else:
            with engine.connect() as conn:
                row = repo.get_user_by_email_global(conn, email)
                if row and row.get("is_active"):
                    candidate = DbUser(
                        row["id"], row["username"], row["password_hash"],
                        row["must_change_password"], row["tenant_id"], row["role"],
                    )
                    if candidate.check_password(password):
                        user = candidate

        if user:
            login_user(user)
            logger.info(f"Login bem-sucedido: '{email}'.")
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("respostas"))

        logger.warning(f"Tentativa de login inválida: '{email}'.")
        flash("Email ou senha inválidos.", "danger")
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
        name: email
        description: Endereço de email cadastrado
        type: string
        required: true
    responses:
      302:
        description: Sempre redireciona para /login com mensagem genérica
      200:
        description: Formulário de solicitação
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        email_to_send = None
        username_to_send = None
        token_to_send = None

        with engine.connect() as conn:
            row = repo.get_user_by_email_global(conn, email)

            if row and row.get("email"):
                token = uuid.uuid4().hex
                expires = datetime.utcnow() + timedelta(hours=1)
                conn.execute(
                    text("""INSERT INTO password_reset_tokens
                            (user_id, token, expires_at) VALUES (:uid, :tok, :exp)"""),
                    {"uid": row["id"], "tok": token, "exp": expires},
                )
                conn.commit()
                base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
                email_to_send = row["email"]
                username_to_send = row["username"]
                token_to_send = f"{base_url}/reset_password/{token}"

        if email_to_send:
            try:
                send_reset_email(email_to_send, username_to_send, token_to_send)
            except Exception as e:
                logger.error(f"Erro ao enviar email de reset: {e}")

        flash(
            "Se o email estiver cadastrado, você receberá um link de redefinição em breve.",
            "info",
        )
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


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
        confirm = request.form.get("confirm_password", "")

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
            tok_row = repo.get_valid_reset_token(conn, token)
            if not tok_row:
                flash("Link de redefinição inválido ou expirado.", "danger")
                return redirect(url_for("forgot_password"))
            conn.execute(
                text(
                    "UPDATE users SET password_hash=:pw, must_change_password=FALSE WHERE id=:id"
                ),
                {"pw": generate_password_hash(new_password), "id": tok_row["user_id"]},
            )
            conn.execute(
                text("UPDATE password_reset_tokens SET used=TRUE WHERE id=:id"),
                {"id": tok_row["id"]},
            )
            conn.commit()

        logger.info(f"Senha redefinida via token para user_id={tok_row['user_id']}.")
        flash("Senha redefinida com sucesso! Faça login com sua nova senha.", "success")
        return redirect(url_for("login"))

    with engine.connect() as conn:
        tok_row = repo.get_valid_reset_token(conn, token)
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
        result = repo.get_invitee_by_token(conn, token)
        if not result:
            abort(404)
        if request.method == "POST":
            response = request.form.get("response")
            observacao = request.form.get("observacao") or None
            if result["response"] == "pending" and response in ["yes", "no"]:
                repo.update_invitee(
                    conn, result["tenant_id"], result["id"],
                    response=response,
                    observation=observacao,
                    responded_at=datetime.utcnow(),
                )
                conn.commit()
                logger.info(
                    f"Resposta: {result['name']} -> {response} | Obs: {observacao}"
                )
            return redirect(url_for("invite", token=token))

        texts = repo.get_event_texts(conn, result["tenant_id"], result["event_id"])
        return render_template(
            "invite.html",
            invitee=result,
            question_text=texts.get("question_text"),
            yes_text=texts.get("yes_text"),
            no_text=texts.get("no_text"),
            post_yes_text=texts.get("post_yes_text"),
            post_no_text=texts.get("post_no_text"),
        )


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
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 50
    search = request.args.get("search", "").strip()
    offset = (page - 1) * per_page

    tid = current_user.tenant_id
    is_admin = current_user.is_super_admin
    owner_uid = None if is_admin else current_user.db_id

    with engine.connect() as conn:
        convidados_raw = repo.get_invitees(
            conn, tid,
            owner_user_id=owner_uid,
            search=search,
            limit=per_page,
            offset=offset,
        )
        counts = repo.count_invitees_by_response(
            conn, tid, owner_user_id=owner_uid, search=search
        )
        event_id = repo.get_default_event_id(conn, tid)
        texts = repo.get_event_texts(conn, tid, event_id)

    tz_offset = int(os.getenv("TZ_OFFSET_HOURS", "-3"))
    convidados = []
    for r in convidados_raw:
        row = dict(r)
        if row["response_date"]:
            row["response_date"] += timedelta(hours=tz_offset)
        if row["phone"]:
            phone_clean = (
                row["phone"]
                .replace("(", "")
                .replace(")", "")
                .replace("-", "")
                .replace(" ", "")
            )
            invite_url = url_for("invite", token=row["token"], _external=True)
            message = f"{texts.get('question_text', '')} {invite_url}"
            row["whatsapp_url"] = (
                f"https://wa.me/55{phone_clean}?text={quote_plus(message, encoding='utf-8')}"
            )
        else:
            row["whatsapp_url"] = None
        convidados.append(row)

    total_convidados = counts["total"]
    total_pages = (total_convidados + per_page - 1) // per_page

    return render_template(
        "admin_responses.html",
        convidados=convidados,
        texts=texts,
        total_sim=counts["total_sim"],
        total_nao=counts["total_nao"],
        total_aguardando=counts["total_aguardando"],
        page=page,
        total_pages=total_pages,
        search=search,
        is_super_admin=is_admin,
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
    search = request.args.get("search", "").strip()
    tid = current_user.tenant_id
    is_admin = current_user.is_super_admin
    owner_uid = None if is_admin else current_user.db_id

    with engine.connect() as conn:
        result = repo.get_invitees(
            conn, tid, owner_user_id=owner_uid, search=search, limit=10000
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Convidados"
    ws.append(
        ["Nome", "Email", "Telefone", "Resposta", "Data/Hora", "Observação", "Arquivo"]
    )
    for r in result:
        response_display = "" if r["response"] == "pending" else (r["response"] or "")
        ws.append(
            [
                r["name"],
                r["email"] or "",
                r["phone"] or "",
                response_display,
                r["response_date"].strftime("%d/%m/%Y %H:%M")
                if r["response_date"]
                else "",
                r["custom_message"] or "",
                r["media_url"] or "",
            ]
        )
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
        headers={"Content-Disposition": "attachment;filename=convidados.xlsx"},
    )


@app.route("/admin/convidados/add", methods=["POST"])
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
    name = request.form.get("name", "").strip()
    if not name:
        flash("Nome é obrigatório.", "danger")
        return redirect(url_for("respostas"))

    email = request.form.get("email") or None
    phone = request.form.get("phone") or None
    msg = request.form.get("custom_message") or None

    media_filename = None
    file = request.files.get("media_file")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Arquivo inválido. Use .jpg/.jpeg/.png ou .mp4 (até 20MB).", "danger")
            return redirect(url_for("respostas"))
        media_filename = save_uploaded_file(file)
        if media_filename is None:
            flash("Erro ao salvar arquivo. Tente novamente.", "danger")
            return redirect(url_for("respostas"))

    tid = current_user.tenant_id
    token = secrets.token_urlsafe(16)[:22]
    with engine.connect() as conn:
        event_id = repo.get_default_event_id(conn, tid)
        repo.add_invitee(
            conn, tid, event_id, name, token,
            phone=phone, email=email, observation=msg, media_url=media_filename,
        )
        conn.commit()

    logger.info(f"Convidado adicionado: '{name}' por '{current_user.username}'.")
    flash(f'Convidado "{name}" adicionado com sucesso!', "success")
    return redirect(url_for("respostas"))


@app.route("/admin/convidados/<int:id>/edit", methods=["POST"])
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
    tid = current_user.tenant_id
    with engine.connect() as conn:
        guest = repo.get_invitee(conn, tid, id)

    if not guest:
        abort(404)
    if not current_user.is_super_admin and guest["event_owner_user_id"] != current_user.db_id:
        abort(403)

    name = request.form.get("name", "").strip()
    email = request.form.get("email") or None
    phone = request.form.get("phone") or None
    msg = request.form.get("custom_message") or None
    response_val = request.form.get("response")
    if response_val not in ("yes", "no", ""):
        response_val = ""
    response_db = "pending" if response_val == "" else response_val

    new_media = None
    file = request.files.get("media_file")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Arquivo inválido. Use .jpg/.jpeg/.png ou .mp4 (até 20MB).", "danger")
            return redirect(url_for("respostas"))
        new_media = save_uploaded_file(file)
        if new_media is None:
            flash("Erro ao salvar arquivo. Tente novamente.", "danger")
            return redirect(url_for("respostas"))

    update_fields = dict(
        name=name, email=email, phone=phone, observation=msg, response=response_db
    )
    if new_media:
        update_fields["media_url"] = new_media

    with engine.connect() as conn:
        repo.update_invitee(conn, tid, id, **update_fields)
        conn.commit()

    logger.info(f"Convidado id={id} atualizado por '{current_user.username}'.")
    flash("Convidado atualizado com sucesso!", "success")
    return redirect(url_for("respostas"))


@app.route("/admin/convidados/<int:id>/delete", methods=["POST"])
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
    tid = current_user.tenant_id
    with engine.connect() as conn:
        res = repo.get_invitee(conn, tid, id)

    if not res:
        abort(404)
    if not current_user.is_super_admin and res["event_owner_user_id"] != current_user.db_id:
        abort(403)

    with engine.connect() as conn:
        repo.delete_invitee(conn, tid, id)
        conn.commit()

    if res["media_url"]:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], res["media_url"]))
        except FileNotFoundError:
            pass

    logger.info(
        f"Convidado '{res['name']}' (id={id}) excluído por '{current_user.username}'."
    )
    flash("Convidado excluído com sucesso.", "warning")
    return redirect(url_for("respostas"))


@app.route("/admin/textos", methods=["POST"])
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
        "question_text": request.form.get("question_text") or "",
        "yes_text": request.form.get("yes_text") or "",
        "no_text": request.form.get("no_text") or "",
        "post_yes_text": request.form.get("post_yes_text") or "",
        "post_no_text": request.form.get("post_no_text") or "",
    }
    tid = current_user.tenant_id
    with engine.connect() as conn:
        event_id = repo.get_default_event_id(conn, tid)
        repo.update_event_texts(conn, tid, event_id, **textos)
        conn.commit()
    logger.info(f"Textos do convite atualizados por '{current_user.username}'.")
    flash("Textos atualizados com sucesso!", "success")
    return redirect(url_for("respostas"))


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
    tid = current_user.tenant_id
    with engine.connect() as conn:
        users = repo.get_users(conn, tid)
        users_list = [
            u | {"guest_count": repo.count_invitees_for_user(conn, tid, u["id"])}
            for u in users
        ]
    return render_template(
        "admin_users.html", users=users_list, default_password=DEFAULT_PASSWORD
    )


@app.route("/admin/usuarios/add", methods=["POST"])
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
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    whatsapp = request.form.get("whatsapp", "").strip() or None

    if not username:
        flash("Nome de usuário é obrigatório.", "danger")
        return redirect(url_for("admin_usuarios"))
    if not email:
        flash("Email é obrigatório.", "danger")
        return redirect(url_for("admin_usuarios"))

    tid = current_user.tenant_id
    try:
        with engine.connect() as conn:
            repo.add_user(
                conn, tid, username, email,
                generate_password_hash(DEFAULT_PASSWORD),
                role="member",
                whatsapp=whatsapp,
                must_change_password=True,
            )
            conn.commit()
        logger.info(f"Usuário '{username}' criado por '{current_user.username}'.")
        flash(
            f'Usuário "{username}" criado. Senha padrão: {DEFAULT_PASSWORD}', "success"
        )
    except Exception:
        flash("Erro: nome de usuário ou email já existe.", "danger")

    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:id>/edit", methods=["POST"])
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
    new_username = request.form.get("username", "").strip()
    new_email = request.form.get("email", "").strip()
    new_whatsapp = request.form.get("whatsapp", "").strip() or None

    if not new_username:
        flash("Nome de usuário não pode ser vazio.", "danger")
        return redirect(url_for("admin_usuarios"))
    if not new_email:
        flash("Email é obrigatório.", "danger")
        return redirect(url_for("admin_usuarios"))

    tid = current_user.tenant_id
    with engine.connect() as conn:
        user = repo.get_user_by_id(conn, tid, id)
    if not user:
        abort(404)

    try:
        with engine.connect() as conn:
            repo.update_user(
                conn, tid, id,
                username=new_username, email=new_email, whatsapp=new_whatsapp,
            )
            conn.commit()
        logger.info(f"Usuário id={id} atualizado por '{current_user.username}'.")
        flash(f'Usuário "{new_username}" atualizado.', "success")
    except Exception:
        flash("Erro: nome de usuário ou email já existe.", "danger")

    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:id>/reset_senha", methods=["POST"])
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
    tid = current_user.tenant_id
    with engine.connect() as conn:
        user = repo.get_user_by_id(conn, tid, id)
        if not user:
            abort(404)
        repo.update_user(
            conn, tid, id,
            password_hash=generate_password_hash(DEFAULT_PASSWORD),
            must_change_password=True,
        )
        conn.commit()
    logger.info(
        f"Senha de '{user['username']}' (id={id}) resetada por '{current_user.username}'."
    )
    flash(f'Senha de "{user["username"]}" resetada para a senha padrão.', "success")
    return redirect(url_for("admin_usuarios"))


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
        return redirect(url_for("respostas"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

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
            repo.update_user(
                conn, current_user.tenant_id, current_user.db_id,
                password_hash=generate_password_hash(new_password),
                must_change_password=False,
            )
            conn.commit()

        login_user(load_user(current_user.id))
        logger.info(f"Usuário '{current_user.username}' alterou sua senha.")
        flash("Senha alterada com sucesso!", "success")
        return redirect(url_for("respostas"))

    return render_template("change_password.html")


@app.route("/admin/usuarios/<int:id>/delete", methods=["POST"])
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
    tid = current_user.tenant_id
    with engine.connect() as conn:
        user = repo.get_user_by_id(conn, tid, id)
        if not user:
            abort(404)
        repo.delete_user(conn, tid, id)
        conn.commit()

    logger.info(
        f"Usuário '{user['username']}' (id={id}) excluído por '{current_user.username}'."
    )
    flash(
        f'Usuário "{user["username"]}" excluído.',
        "warning",
    )
    return redirect(url_for("admin_usuarios"))


if __name__ == "__main__":
    logger.info(f"Comemore+ iniciado. Versão: {APP_VERSION}")
    app.run(host="0.0.0.0", port=8000)
