# backend\app.py

from flask import Flask, render_template, request, redirect, url_for, abort, Response, flash
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
import pymysql
import os
import uuid
from datetime import timedelta
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'insira_uma_chave_secreta_aqui')

# ---- LOGIN SETUP ----
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

def get_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST','localhost'),
        user=os.getenv('DB_USER','root'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        init_command='SET NAMES utf8mb4'
    )

@app.route('/invite/<token>', methods=['GET','POST'])
def invite(token):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM invitees WHERE token=%s", (token,))
        invitee = cursor.fetchone()

        cursor.execute(
            "SELECT `key`,`value` FROM settings WHERE `key` IN "
            "('question_text','yes_text','no_text','post_yes_text','post_no_text')"
        )
        texts = {r['key']: r['value'] for r in cursor.fetchall()}

    if not invitee:
        abort(404)

    if request.method == 'POST':
        response = request.form.get('response')
        if invitee['response'] is None and response in ['yes','no']:
            with conn.cursor() as cursor2:
                cursor2.execute(
                    "UPDATE invitees SET response=%s, response_date=NOW() WHERE token=%s",
                    (response, token)
                )
            conn.commit()
        return redirect(url_for('invite', token=token))

    return render_template(
        'invite.html',
        invitee=invitee,
        question_text = texts.get('question_text'),
        yes_text      = texts.get('yes_text'),
        no_text       = texts.get('no_text'),
        post_yes_text = texts.get('post_yes_text'),
        post_no_text  = texts.get('post_no_text')
    )

@app.route("/admin/respostas")
@login_required
def respostas():
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT id,name,email,phone,response,response_date,token
            FROM invitees
            ORDER BY response_date IS NULL, response_date DESC
        """)
        convidados = cursor.fetchall()

        for row in convidados:
            if row['response_date']:
                row['response_date'] -= timedelta(hours=3)

        cursor.execute(
            "SELECT `key`,`value` FROM settings WHERE `key` IN "
            "('question_text','yes_text','no_text','post_yes_text','post_no_text')"
        )
        texts = {r['key']: r['value'] for r in cursor.fetchall()}

    for row in convidados:
        if row['phone']:
            phone_clean = (
                row['phone'].replace("(", "")
                            .replace(")", "")
                            .replace("-", "")
                            .replace(" ", "")
            )
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
    name  = request.form.get('name')
    email = request.form.get('email') or None
    phone = request.form.get('phone')
    msg   = request.form.get('custom_message') or None

    if not name:
        flash("Nome é obrigatório.", "danger")
        return redirect(url_for('respostas'))

    token = uuid.uuid4().hex
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invitees (name,email,phone,token,custom_message) "
            "VALUES (%s,%s,%s,%s,%s)",
            (name,email,phone,token,msg)
        )
    conn.commit()
    flash(f"Convidado “{name}” adicionado com sucesso!", "success")
    return redirect(url_for('respostas'))

@app.route("/admin/convidados/<int:id>/delete", methods=['POST'])
@login_required
def delete_convidado(id):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM invitees WHERE id=%s", (id,))
    conn.commit()
    flash("Convidado excluído com sucesso.", "warning")
    return redirect(url_for('respostas'))

@app.route("/admin/textos", methods=['POST'])
@login_required
def update_textos():
    q  = request.form.get('question_text') or ""
    y  = request.form.get('yes_text') or ""
    n  = request.form.get('no_text') or ""
    py = request.form.get('post_yes_text') or ""
    pn = request.form.get('post_no_text') or ""
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('question_text',%s)", (q,))
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('yes_text',%s)", (y,))
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('no_text',%s)", (n,))
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('post_yes_text',%s)", (py,))
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('post_no_text',%s)", (pn,))
    conn.commit()
    flash("Textos atualizados com sucesso!", "success")
    return redirect(url_for('respostas'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
