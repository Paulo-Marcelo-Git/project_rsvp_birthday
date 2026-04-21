# backend/app.py

import os
import time
import logging
from functools import wraps
from dotenv import load_dotenv
from datetime import timedelta
from urllib.parse import quote_plus
from flask import Flask, render_template, request, redirect, url_for, abort, flash, Response
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from werkzeug.security import check_password_hash, generate_password_hash
from io import BytesIO
from openpyxl import Workbook
from werkzeug.utils import secure_filename
import uuid

load_dotenv()

APP_VERSION = "Comemore+ v1.2.1"

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

DEFAULT_PASSWORD = "102030@"

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

# Rotas
@app.route("/login", methods=["GET", "POST"])
def login():
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
    logout_user()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("login"))

@app.route("/invite/<token>", methods=["GET", "POST"])
@csrf.exempt
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
    page = max(1, int(request.args.get('page', 1)))
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
    with engine.connect() as conn:
        users = conn.execute(
            text("SELECT id, username, created_at FROM users ORDER BY created_at DESC")
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
    username = request.form.get('username', '').strip()
    if not username:
        flash("Nome de usuário é obrigatório.", "danger")
        return redirect(url_for('admin_usuarios'))

    try:
        with engine.connect() as conn:
            conn.execute(
                text("""INSERT INTO users (username, password_hash, must_change_password)
                        VALUES (:u, :pw, TRUE)"""),
                {"u": username, "pw": generate_password_hash(DEFAULT_PASSWORD)}
            )
            conn.commit()
        logger.info(f"Usuário '{username}' criado por '{current_user.username}'.")
        flash(f'Usuário "{username}" criado. Senha padrão: {DEFAULT_PASSWORD}', "success")
    except Exception:
        flash("Erro: nome de usuário já existe.", "danger")

    return redirect(url_for('admin_usuarios'))

@app.route("/admin/usuarios/<int:id>/edit", methods=['POST'])
@login_required
@super_admin_required
def edit_usuario(id):
    new_username = request.form.get('username', '').strip()
    if not new_username:
        flash("Nome de usuário não pode ser vazio.", "danger")
        return redirect(url_for('admin_usuarios'))

    try:
        with engine.connect() as conn:
            user = conn.execute(
                text("SELECT username FROM users WHERE id=:id"), {"id": id}
            ).mappings().fetchone()
            if not user:
                abort(404)
            conn.execute(
                text("UPDATE users SET username=:u WHERE id=:id"),
                {"u": new_username, "id": id}
            )
            conn.commit()
        logger.info(f"Usuário id={id} renomeado para '{new_username}' por '{current_user.username}'.")
        flash(f'Usuário renomeado para "{new_username}".', "success")
    except Exception:
        flash("Erro: nome de usuário já existe.", "danger")

    return redirect(url_for('admin_usuarios'))

@app.route("/admin/usuarios/<int:id>/reset_senha", methods=['POST'])
@login_required
@super_admin_required
def reset_senha_usuario(id):
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
