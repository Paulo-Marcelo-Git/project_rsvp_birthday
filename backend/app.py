# backend/app.py

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
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
    send_file,
    session,
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
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from openpyxl import Workbook
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import repo
import tasks
from queue_utils import enqueue_email

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

limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=os.getenv("REDIS_URL", "memory://"),
    default_limits=[],
)


@app.errorhandler(429)
def ratelimit_handler(e):
    retry = getattr(e, "retry_after", None)
    return render_template("429.html", retry_after=retry), 429


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
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/app/uploads")
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

# Auth
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


class DbUser(UserMixin):
    def __init__(
        self,
        db_id,
        username,
        password_hash,
        must_change_password=False,
        tenant_id=1,
        role="member",
        email=None,
    ):
        self.id = f"user_{db_id}"
        self.db_id = db_id
        self.username = username
        self._password_hash = password_hash
        self.must_change_password = bool(must_change_password)
        self.tenant_id = tenant_id
        self.role = role
        self.email = email

    @property
    def is_tenant_admin(self):
        return self.role == "tenant_admin"

    def check_password(self, password):
        return check_password_hash(self._password_hash, password)


@login_manager.user_loader
def load_user(user_id):
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
                        "must_change_password, role, email "
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
                    email=row.get("email"),
                )
    return None


def tenant_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_tenant_admin:
            abort(403)
        return f(*args, **kwargs)

    return decorated


def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        superadmin_email = os.getenv("SUPERADMIN_EMAIL", "")
        if not superadmin_email:
            abort(403)
        if current_user.role == "tenant_admin" and current_user.email == superadmin_email:
            logger.warning(
                f"SUPERADMIN_EMAIL '{superadmin_email}' pertence a um tenant_admin "
                "— configuração inválida. Acesse /superadmin com uma conta sem tenant."
            )
            abort(403)
        if current_user.email != superadmin_email:
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
        if not current_user.is_authenticated or not current_user.is_tenant_admin:
            return redirect(url_for("login"))


@app.before_request
def force_password_change():
    if (
        current_user.is_authenticated
        and not current_user.is_tenant_admin
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



# Rotas
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
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

        with engine.connect() as conn:
            row = repo.get_user_by_email_global(conn, email)
            if row and not row.get("is_active"):
                logger.warning(f"Login bloqueado (email não verificado): '{email}'.")
                flash(
                    "Confirme seu email antes de fazer login. "
                    "Verifique sua caixa de entrada ou solicite novo link.",
                    "warning",
                )
                return render_template("login.html")
            if row and row.get("is_active"):
                candidate = DbUser(
                    row["id"], row["username"], row["password_hash"],
                    row["must_change_password"], row["tenant_id"], row["role"],
                )
                if candidate.check_password(password):
                    status = repo.get_tenant_status(conn, row["tenant_id"])
                    if status == "suspended":
                        logger.warning(f"Login bloqueado (tenant suspenso): '{email}'.")
                        flash(
                            "Sua conta está suspensa. "
                            "Entre em contato com o suporte.",
                            "danger",
                        )
                        return render_template("login.html")
                    user = candidate

        if user:
            login_user(user)
            logger.info(f"Login bem-sucedido: '{email}'.")
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("respostas"))

        logger.warning(f"Tentativa de login inválida: '{email}'.")
        flash("Email ou senha inválidos.", "danger")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def signup():
    """Cadastro self-service: cria tenant + admin + evento padrão atomicamente."""
    skip_verification = os.getenv("SKIP_EMAIL_VERIFICATION", "").lower() in (
        "1", "true", "yes"
    )

    if request.method == "POST":
        nome = request.form.get("nome_anfitriao", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if len(nome) < 2:
            errors.append("Nome do anfitrião é obrigatório (mínimo 2 caracteres).")
        if "@" not in email or "." not in email:
            errors.append("Email inválido.")
        if len(password) < 8:
            errors.append("Senha deve ter pelo menos 8 caracteres.")
        if password != confirm:
            errors.append("Senhas não conferem.")
        if not request.form.get("accept_terms"):
            errors.append("Você deve aceitar os Termos de Uso para continuar.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template("signup.html")

        if not skip_verification:
            if not os.getenv("EMAIL_SMTP") or not os.getenv("EMAIL_USER"):
                logger.error("Signup bloqueado: EMAIL_SMTP/EMAIL_USER não configurados.")
                flash(
                    "Servidor de email não configurado. Contate o administrador.",
                    "danger",
                )
                return render_template("signup.html"), 500

        with engine.connect() as conn:
            existing = repo.get_user_by_email_global(conn, email)

            if existing:
                if existing.get("is_active"):
                    flash("Este email já está cadastrado. Faça login.", "info")
                    return redirect(url_for("login"))
                # Conta existe mas não verificada: reenviar token
                repo.invalidate_verification_tokens(conn, existing["id"])
                if skip_verification:
                    conn.execute(
                        text("UPDATE users SET is_active = 1 WHERE id = :uid"),
                        {"uid": existing["id"]},
                    )
                    conn.commit()
                    flash("Conta ativada com sucesso. Faça login.", "success")
                    return redirect(url_for("login"))
                token = repo.create_email_verification_token(conn, existing["id"])
                conn.commit()
                base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
                enqueue_email(tasks.send_verification_email, email, f"{base_url}/verify-email/{token}")
                return render_template("verify_email_sent.html", email=email)

            password_hash = generate_password_hash(password)
            accepted_terms_at = datetime.now(timezone.utc).replace(tzinfo=None)
            try:
                tenant_id = repo.create_tenant(conn, nome)
                user_id = repo.create_tenant_admin_user(
                    conn, tenant_id, email, password_hash,
                    accepted_terms_at=accepted_terms_at,
                )
                repo.create_default_event(conn, tenant_id, nome, owner_user_id=user_id)
                if skip_verification:
                    conn.execute(
                        text("UPDATE users SET is_active = 1 WHERE id = :uid"),
                        {"uid": user_id},
                    )
                    conn.commit()
                    flash("Conta criada com sucesso! Faça login.", "success")
                    return redirect(url_for("login"))
                token = repo.create_email_verification_token(conn, user_id)
                conn.commit()
            except Exception as e:
                logger.error(f"Erro ao criar conta para '{email}': {e}")
                flash("Erro ao criar conta. Tente novamente mais tarde.", "danger")
                return render_template("signup.html")

        base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
        enqueue_email(tasks.send_verification_email, email, f"{base_url}/verify-email/{token}")
        return render_template("verify_email_sent.html", email=email)

    return render_template("signup.html")


@app.route("/verify-email/<token>")
def verify_email(token):
    """Ativa conta via token de verificação de email."""
    with engine.connect() as conn:
        row = repo.get_valid_verification_token(conn, token)
        if not row:
            flash(
                "Link de verificação inválido ou expirado. Solicite um novo.",
                "danger",
            )
            return redirect(url_for("resend_verification"))
        repo.use_verification_token(conn, row["id"], row["user_id"])
        conn.commit()

    flash("Email confirmado! Faça login.", "success")
    return redirect(url_for("login"))


@app.route("/resend-verification", methods=["GET", "POST"])
def resend_verification():
    """Reenvia link de verificação de email para conta pendente."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        with engine.connect() as conn:
            row = repo.get_user_by_email_global(conn, email)
            if row and not row.get("is_active"):
                repo.invalidate_verification_tokens(conn, row["id"])
                token = repo.create_email_verification_token(conn, row["id"])
                conn.commit()
                base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
                enqueue_email(tasks.send_verification_email, email, f"{base_url}/verify-email/{token}")
        flash(
            "Se o email estiver cadastrado e pendente de verificação, "
            "você receberá um novo link em breve.",
            "info",
        )
        return redirect(url_for("login"))
    return render_template("resend_verification.html")


@app.route("/termos")
def termos():
    return render_template("termos.html")


@app.route("/privacidade")
def privacidade():
    return render_template("privacidade.html")


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
@limiter.limit("5 per hour", methods=["POST"])
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
        email = request.form.get("email", "").strip().lower()
        email_to_send = None
        username_to_send = None
        token_to_send = None

        with engine.connect() as conn:
            row = repo.get_user_by_email_global(conn, email)

            if row and row.get("email"):
                token = uuid.uuid4().hex
                expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
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
            enqueue_email(tasks.send_reset_email, email_to_send, username_to_send, token_to_send)

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
@limiter.limit("30 per minute", methods=["GET"])
@limiter.limit("10 per minute", methods=["POST"])
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
                    responded_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                conn.commit()
                logger.info(
                    f"Resposta: {result['name']} -> {response} | Obs: {observacao}"
                )
            return redirect(url_for("invite", token=token))

        session["invite_token"] = token
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


@app.route("/uploads/<filename>")
def serve_upload(filename):
    """
    Serve arquivo de upload com validação de posse.

    Caminho 1 — usuário autenticado: verifica que o arquivo pertence ao
    tenant do usuário logado.
    Caminho 2 — convidado sem login: valida via session['invite_token'] que
    o token corresponde a um invitee cujo media_url é este filename.
    Sem query string: o token não aparece em logs de servidor.
    """
    safe = secure_filename(filename)
    if not safe or safe != filename:
        abort(404)

    if not current_user.is_authenticated and not session.get("invite_token"):
        abort(404)

    with engine.connect() as conn:
        if current_user.is_authenticated:
            owner_tid = repo.get_media_tenant(conn, safe)
            if owner_tid != current_user.tenant_id:
                abort(404)
        else:
            invite_token = session.get("invite_token")
            invitee = repo.get_invitee_by_token(conn, invite_token)
            if not invitee or invitee.get("media_url") != safe:
                abort(404)

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], safe)
    if not os.path.isfile(filepath):
        abort(404)
    return send_file(filepath)


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
    is_admin = current_user.is_tenant_admin
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
        if event_id is None:
            flash("Nenhum evento encontrado para este tenant. Verifique o cadastro.", "danger")
            return redirect(url_for("admin_usuarios"))
        texts = repo.get_event_texts(conn, tid, event_id)
        limits = repo.get_plan_limits(conn, tid)

    can_manage_members = (
        limits["max_members"] is None or limits["max_members"] > 1
    )

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
        is_tenant_admin=is_admin,
        can_manage_members=can_manage_members,
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
    is_admin = current_user.is_tenant_admin
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
        if event_id is None:
            flash("Nenhum evento encontrado. Não é possível adicionar convidados.", "danger")
            return redirect(url_for("respostas"))
        limits = repo.get_plan_limits(conn, tid)
        current_count = repo.count_invitees_for_event(conn, tid, event_id)
        if not repo.within_limit(current_count, limits["max_invitees"]):
            flash(
                f"Limite de {limits['max_invitees']} convidados por evento atingido. "
                "Faça upgrade do plano para adicionar mais.",
                "danger",
            )
            return redirect(url_for("respostas"))
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
    if not current_user.is_tenant_admin and guest["event_owner_user_id"] != current_user.db_id:
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
    if not current_user.is_tenant_admin and res["event_owner_user_id"] != current_user.db_id:
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
@tenant_admin_required
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
        if event_id is None:
            flash("Nenhum evento encontrado. Não é possível salvar os textos.", "danger")
            return redirect(url_for("respostas"))
        repo.update_event_texts(conn, tid, event_id, **textos)
        conn.commit()
    logger.info(f"Textos do convite atualizados por '{current_user.username}'.")
    flash("Textos atualizados com sucesso!", "success")
    return redirect(url_for("respostas"))


# ===== Gerenciamento de Usuários =====


@app.route("/admin/usuarios")
@login_required
@tenant_admin_required
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
        limits = repo.get_plan_limits(conn, tid)
        member_count = repo.count_members_for_tenant(conn, tid)
        users = repo.get_users(conn, tid)
        users_list = [
            u | {"guest_count": repo.count_invitees_for_user(conn, tid, u["id"])}
            for u in users
        ]
    max_members = limits["max_members"]
    can_add_member = repo.within_limit(member_count, max_members)
    smtp_configured = bool(os.getenv("EMAIL_SMTP") and os.getenv("EMAIL_USER"))
    return render_template(
        "admin_users.html",
        users=users_list,
        smtp_configured=smtp_configured,
        member_count=member_count,
        max_members=max_members,
        can_add_member=can_add_member,
    )


@app.route("/admin/usuarios/add", methods=["POST"])
@login_required
@tenant_admin_required
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
    with engine.connect() as conn:
        limits = repo.get_plan_limits(conn, tid)
        current_count = repo.count_members_for_tenant(conn, tid)
    if not repo.within_limit(current_count, limits["max_members"]):
        flash(
            f"Limite de {limits['max_members']} membro(s) atingido. "
            "Faça upgrade do plano para adicionar mais.",
            "danger",
        )
        return redirect(url_for("admin_usuarios"))

    temp_pass = secrets.token_urlsafe(12)
    try:
        with engine.connect() as conn:
            new_user_id = repo.add_user(
                conn, tid, username, email,
                generate_password_hash(temp_pass),
                role="member",
                whatsapp=whatsapp,
                must_change_password=True,
            )
            conn.commit()
        logger.info(f"Usuário '{username}' criado por '{current_user.username}'.")

        if os.getenv("EMAIL_SMTP") and os.getenv("EMAIL_USER"):
            with engine.connect() as conn:
                token = uuid.uuid4().hex
                expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
                conn.execute(
                    text("INSERT INTO password_reset_tokens (user_id, token, expires_at) "
                         "VALUES (:uid, :tok, :exp)"),
                    {"uid": new_user_id, "tok": token, "exp": expires},
                )
                conn.commit()
            base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
            reset_url = f"{base_url}/reset_password/{token}"
            enqueue_email(tasks.send_member_invite_email, email, username, reset_url)
            flash(f'Usuário "{username}" criado. Email de convite enviado para {email}.', "success")
        else:
            flash(
                f'Usuário "{username}" criado. Senha temporária: {temp_pass} '
                f'(o usuário deve trocá-la no primeiro acesso).',
                "success",
            )
    except Exception:
        flash("Erro: nome de usuário ou email já existe.", "danger")

    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:id>/edit", methods=["POST"])
@login_required
@tenant_admin_required
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
@tenant_admin_required
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
        temp_pass = secrets.token_urlsafe(12)
        repo.update_user(
            conn, tid, id,
            password_hash=generate_password_hash(temp_pass),
            must_change_password=True,
        )
        conn.commit()
    logger.info(
        f"Senha de '{user['username']}' (id={id}) resetada por '{current_user.username}'."
    )

    if os.getenv("EMAIL_SMTP") and os.getenv("EMAIL_USER") and user.get("email"):
        with engine.connect() as conn:
            token = uuid.uuid4().hex
            from datetime import timezone
            expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
            conn.execute(
                text("INSERT INTO password_reset_tokens (user_id, token, expires_at) "
                     "VALUES (:uid, :tok, :exp)"),
                {"uid": id, "tok": token, "exp": expires},
            )
            conn.commit()
        base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
        reset_url = f"{base_url}/reset_password/{token}"
        enqueue_email(tasks.send_member_invite_email, user["email"], user["username"], reset_url)
        flash(f'Senha de "{user["username"]}" resetada. Email com link enviado para {user["email"]}.', "success")
    else:
        flash(
            f'Senha de "{user["username"]}" resetada. Senha temporária: {temp_pass} '
            f'(o usuário deve trocá-la no próximo acesso).',
            "success",
        )
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
    if current_user.is_tenant_admin:
        return redirect(url_for("respostas"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

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
@tenant_admin_required
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


# ── Super-admin ───────────────────────────────────────────────────────────────

@app.route("/superadmin")
@superadmin_required
def superadmin():
    """Painel super-admin: lista todos os tenants com plano e uso."""
    with engine.connect() as conn:
        tenants = repo.list_all_tenants(conn)
    return render_template("superadmin.html", tenants=tenants)


@app.route("/superadmin/tenant/<int:tenant_id>/set_plan", methods=["POST"])
@superadmin_required
def superadmin_set_plan(tenant_id):
    plan = request.form.get("plan", "").strip()
    if plan not in ("free", "pro", "business"):
        flash("Plano inválido.", "danger")
        return redirect(url_for("superadmin"))
    with engine.connect() as conn:
        repo.set_tenant_plan(conn, tenant_id, plan)
        conn.commit()
    flash(f"Plano do tenant {tenant_id} alterado para '{plan}'.", "success")
    return redirect(url_for("superadmin"))


@app.route("/superadmin/tenant/<int:tenant_id>/suspend", methods=["POST"])
@superadmin_required
def superadmin_suspend(tenant_id):
    with engine.connect() as conn:
        repo.set_tenant_status(conn, tenant_id, "suspended")
        conn.commit()
    flash(f"Tenant {tenant_id} suspenso.", "warning")
    return redirect(url_for("superadmin"))


@app.route("/superadmin/tenant/<int:tenant_id>/reactivate", methods=["POST"])
@superadmin_required
def superadmin_reactivate(tenant_id):
    with engine.connect() as conn:
        repo.set_tenant_status(conn, tenant_id, "active")
        conn.commit()
    flash(f"Tenant {tenant_id} reativado.", "success")
    return redirect(url_for("superadmin"))


if __name__ == "__main__":
    logger.info(f"Comemore+ iniciado. Versão: {APP_VERSION}")
    app.run(host="0.0.0.0", port=8000)
