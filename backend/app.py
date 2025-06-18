# backend/app.py

import os
import logging
from dotenv import load_dotenv
from datetime import timedelta
from urllib.parse import quote_plus
from flask import Flask, render_template, request, redirect, url_for, abort, flash
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# Carregar variáveis de ambiente
load_dotenv()

# Definir versão
APP_VERSION = "Comemore+ v2.1.0"

# Setup de logging
log_path = os.getenv("LOG_FILE", "logs/app.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Injetar versão nos templates
app.config['APP_VERSION'] = APP_VERSION

@app.context_processor
def inject_version():
    return dict(app_version=app.config['APP_VERSION'])

# SQLAlchemy Pooling com mapeamento automático para dict
db_url = f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
engine = create_engine(
    db_url, 
    poolclass=QueuePool, 
    pool_size=5, 
    max_overflow=10, 
    pool_recycle=3600, 
    future=True
)

# Flask-Login
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

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == os.getenv("ADMIN_USER") and password == os.getenv("ADMIN_PASS"):
            user = AdminUser()
            login_user(user)
            logger.info(f"Login bem-sucedido para: {username}")
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("respostas"))
        logger.warning(f"Tentativa de login inválida: {username}")
        flash("Usuário ou senha inválidos.", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logger.info(f"Logout realizado por: {current_user.id}")
    logout_user()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("login"))

@app.route('/invite/<token>', methods=['GET','POST'])
def invite(token):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM invitees WHERE token=:token"), 
            {"token": token}
        ).mappings().fetchone()

        if not result:
            logger.warning(f"Token inválido acessado: {token}")
            abort(404)

        if request.method == 'POST':
            response = request.form.get('response')
            if result['response'] is None and response in ['yes', 'no']:
                conn.execute(
                    text("UPDATE invitees SET response=:response, response_date=NOW() WHERE token=:token"),
                    {"response": response, "token": token}
                )
                conn.commit()
                logger.info(f"Resposta registrada: {result['name']} -> {response}")
            return redirect(url_for('invite', token=token))

        settings = conn.execute(
            text("""SELECT `key`, `value` FROM settings 
                    WHERE `key` IN 
                    ('question_text','yes_text','no_text','post_yes_text','post_no_text')""")
        ).mappings().all()

        texts = {row['key']: row['value'] for row in settings}

        return render_template(
            'invite.html',
            invitee=result,
            question_text=texts.get('question_text'),
            yes_text=texts.get('yes_text'),
            no_text=texts.get('no_text'),
            post_yes_text=texts.get('post_yes_text'),
            post_no_text=texts.get('post_no_text')
        )

@app.route("/admin/respostas")
@login_required
def respostas():
    logger.info(f"Acesso ao painel de respostas por {current_user.id}")
    with engine.connect() as conn:
        result = conn.execute(
            text("""SELECT id,name,email,phone,response,response_date,token 
                    FROM invitees 
                    ORDER BY response_date IS NULL, response_date DESC""")
        ).mappings().all()

        convidados = []
        for row in result:
            row = dict(row)
            if row['response_date']:
                row['response_date'] -= timedelta(hours=3)
            convidados.append(row)

        settings = conn.execute(
            text("""SELECT `key`,`value` FROM settings 
                    WHERE `key` IN 
                    ('question_text','yes_text','no_text','post_yes_text','post_no_text')""")
        ).mappings().all()

        texts = {row['key']: row['value'] for row in settings}

        for row in convidados:
            if row['phone']:
                phone_clean = row['phone'].replace("(", "").replace(")", "").replace("-", "").replace(" ", "")
                invite_url = url_for('invite', token=row['token'], _external=True)
                message = f"{texts.get('question_text', '')} {invite_url}"
                row['whatsapp_url'] = f"https://wa.me/55{phone_clean}?text={quote_plus(message, encoding='utf-8')}"
            else:
                row['whatsapp_url'] = None

    total_sim = sum(1 for c in convidados if c['response'] == 'yes')
    total_nao = sum(1 for c in convidados if c['response'] == 'no')
    total_aguardando = sum(1 for c in convidados if c['response'] is None)

    return render_template(
        'admin_responses.html',
        convidados=convidados,
        texts=texts,
        total_sim=total_sim,
        total_nao=total_nao,
        total_aguardando=total_aguardando
    )

@app.route("/admin/convidados/add", methods=['POST'])
@login_required
def add_convidado():
    name = request.form.get('name')
    email = request.form.get('email') or None
    phone = request.form.get('phone')
    msg = request.form.get('custom_message') or None

    if not name:
        flash("Nome é obrigatório.", "danger")
        return redirect(url_for('respostas'))

    token = os.urandom(16).hex()
    with engine.connect() as conn:
        conn.execute(
            text("""INSERT INTO invitees (name, email, phone, token, custom_message)
                    VALUES (:name, :email, :phone, :token, :msg)"""),
            {"name": name, "email": email, "phone": phone, "token": token, "msg": msg}
        )
        conn.commit()

    logger.info(f"Novo convidado adicionado: {name}")
    flash(f"Convidado “{name}” adicionado com sucesso!", "success")
    return redirect(url_for('respostas'))

@app.route("/admin/convidados/<int:id>/delete", methods=['POST'])
@login_required
def delete_convidado(id):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT name FROM invitees WHERE id=:id"), {"id": id}
        ).mappings().fetchone()

        conn.execute(text("DELETE FROM invitees WHERE id=:id"), {"id": id})
        conn.commit()

    logger.warning(f"Convidado excluído: {result['name'] if result else 'ID ' + str(id)}")
    flash("Convidado excluído com sucesso.", "warning")
    return redirect(url_for('respostas'))

@app.route("/admin/textos", methods=['POST'])
@login_required
def update_textos():
    textos = {
        "question_text": request.form.get('question_text') or "",
        "yes_text": request.form.get('yes_text') or "",
        "no_text": request.form.get('no_text') or "",
        "post_yes_text": request.form.get('post_yes_text') or "",
        "post_no_text": request.form.get('post_no_text') or ""
    }

    with engine.connect() as conn:
        for key, value in textos.items():
            conn.execute(
                text("REPLACE INTO settings (`key`,`value`) VALUES (:key, :value)"),
                {"key": key, "value": value}
            )
        conn.commit()

    logger.info("Textos do convite atualizados com sucesso.")
    flash("Textos atualizados com sucesso!", "success")
    return redirect(url_for('respostas'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
